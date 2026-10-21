# Copyright 2025 Boson AI and The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# CC-Gen: inference-only port of transformers 5's models/higgs_audio_v2_tokenizer (the audio
# codec OmniVoice speaks through) to transformers 4.57, which has its DAC and HuBERT parts but
# not the codec itself. Training-only initialisation, weight-norm helpers, and the forward()
# round trip are left out; module and parameter names match the checkpoint exactly.

import math
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
from transformers import AutoModel, PretrainedConfig, PreTrainedModel
from transformers.models.auto import CONFIG_MAPPING
from transformers.utils import ModelOutput


class HiggsAudioV2TokenizerConfig(PretrainedConfig):
    model_type = "higgs_audio_v2_tokenizer"

    def __init__(self, target_bandwidths=(0.5, 1, 1.5, 2, 4), sample_rate=24000, kernel_size=3,
                 channel_ratios=(1, 1), strides=(1, 1), block_dilations=(1, 1), unit_kernel_size=3,
                 codebook_size=1024, codebook_dim=64, initializer_range=0.02, acoustic_model_config=None,
                 semantic_model_config=None, semantic_sample_rate=16000, downsample_factor=320, **kwargs):
        self.target_bandwidths = list(target_bandwidths)
        self.sample_rate = sample_rate
        self.kernel_size = kernel_size
        self.channel_ratios = list(channel_ratios)
        self.strides = list(strides)
        self.block_dilations = list(block_dilations)
        self.unit_kernel_size = unit_kernel_size
        self.codebook_size = codebook_size
        self.codebook_dim = codebook_dim
        self.initializer_range = initializer_range
        self.semantic_sample_rate = semantic_sample_rate
        self.downsample_factor = downsample_factor
        acoustic = dict(acoustic_model_config or {})
        acoustic_type = acoustic.pop("model_type", "dac")
        self.acoustic_model_config = CONFIG_MAPPING[acoustic_type](**acoustic) if not isinstance(
            acoustic_model_config, PretrainedConfig) else acoustic_model_config
        semantic = dict(semantic_model_config or {})
        semantic_type = semantic.pop("model_type", "hubert")
        semantic.setdefault("mask_time_prob", 0.0)
        self.semantic_model_config = CONFIG_MAPPING[semantic_type](**semantic) if not isinstance(
            semantic_model_config, PretrainedConfig) else semantic_model_config
        super().__init__(**kwargs)

    @property
    def frame_rate(self):
        return math.ceil(self.sample_rate / self.hop_length)

    @property
    def semantic_hidden_size(self):
        return self.semantic_model_config.hidden_size

    @property
    def hop_length(self):
        return int(np.prod(self.acoustic_model_config.downsampling_ratios))

    @property
    def codebook_nbits(self):
        return math.ceil(math.log2(self.codebook_size))

    @property
    def hidden_size(self):
        return self.acoustic_model_config.hidden_size + self.semantic_model_config.hidden_size

    @property
    def num_quantizers(self):
        return int(1000 * self.target_bandwidths[-1] // (self.frame_rate * self.codebook_nbits))

    @property
    def semantic_downsample_factor(self):
        return int(self.hop_length / (self.sample_rate / self.semantic_sample_rate) / self.downsample_factor)


def _conv1d_output_length(module: nn.Conv1d, length: int) -> int:
    return (length + 2 * module.padding[0] - module.dilation[0] * (module.kernel_size[0] - 1) - 1) // module.stride[0] + 1


class Codebook(nn.Module):
    def __init__(self, config):
        super().__init__()
        embed = torch.zeros(config.codebook_size, config.codebook_dim)
        self.register_buffer("inited", torch.Tensor([True]))
        self.register_buffer("cluster_size", torch.zeros(config.codebook_size))
        self.register_buffer("embed", embed)
        self.register_buffer("embed_avg", embed.clone())

    def encode(self, hidden_states):
        shape = hidden_states.shape
        flat = hidden_states.reshape((-1, shape[-1]))
        embed = self.embed.t()
        dist = -(flat.pow(2).sum(1, keepdim=True) - 2 * flat @ embed + embed.pow(2).sum(0, keepdim=True))
        return dist.max(dim=-1).indices.view(*shape[:-1])

    def decode(self, indices):
        return F.embedding(indices.to(self.embed.device), self.embed)


class VectorQuantization(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.codebook = Codebook(config)
        self.project_in = nn.Linear(config.hidden_size, config.codebook_dim)
        self.project_out = nn.Linear(config.codebook_dim, config.hidden_size)

    def encode(self, hidden_states):
        return self.codebook.encode(self.project_in(hidden_states.permute(0, 2, 1)))

    def decode(self, indices):
        return self.project_out(self.codebook.decode(indices)).permute(0, 2, 1)


class ResidualVectorQuantization(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.quantizers = nn.ModuleList([VectorQuantization(config) for _ in range(config.num_quantizers)])
        self.frame_rate = config.frame_rate
        self.codebook_size = config.codebook_size

    def encode(self, embeddings, bandwidth):
        per_quantizer = math.log2(self.codebook_size) * self.frame_rate / 1000
        count = int(max(1, math.floor(bandwidth / per_quantizer)))
        residual, indices = embeddings, []
        for quantizer in self.quantizers[:count]:
            codes = quantizer.encode(residual)
            residual = residual - quantizer.decode(codes)
            indices.append(codes)
        return torch.stack(indices)

    def decode(self, codes):
        out = torch.full((), 0.0, device=codes.device)
        for i, indices in enumerate(codes):
            out = out + self.quantizers[i].decode(indices).to(codes.device)
        return out


class ResidualUnit(nn.Module):
    def __init__(self, config, in_channels, out_channels, dilation):
        super().__init__()
        self.activation = nn.ELU()
        padding = ((config.unit_kernel_size - 1) // 2) * dilation
        self.conv1 = nn.Conv1d(in_channels, out_channels, config.unit_kernel_size, stride=1, padding=padding,
                               dilation=dilation, bias=False)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size=1, bias=False)

    def forward(self, x):
        y = self.conv2(self.activation(self.conv1(self.activation(x))))
        return x + y


class SemanticEncoderBlock(nn.Module):
    def __init__(self, config, in_channels, out_channels, stride):
        super().__init__()
        self.res_units = nn.ModuleList([ResidualUnit(config, in_channels, in_channels, d) for d in config.block_dilations])
        kernel = 3 if stride == 1 else 2 * stride
        self.conv = nn.Conv1d(in_channels, out_channels, kernel_size=kernel, stride=stride, padding=(kernel - 1) // 2)

    def forward(self, x):
        for unit in self.res_units:
            x = unit(x)
        return self.conv(x)


class SemanticEncoder(nn.Module):
    def __init__(self, config):
        super().__init__()
        size = config.semantic_hidden_size
        self.conv = nn.Conv1d(size, size, config.kernel_size, 1, config.kernel_size // 2, bias=False)
        blocks, in_channels = [], size
        for i, stride in enumerate(config.strides):
            out_channels = int(size * config.channel_ratios[i])
            blocks.append(SemanticEncoderBlock(config, in_channels, out_channels, stride))
            in_channels = out_channels
        self.conv_blocks = nn.ModuleList(blocks)

    def forward(self, x):
        x = self.conv(x)
        for block in self.conv_blocks:
            x = block(x)
        return x


class SemanticDecoderBlock(nn.Module):
    def __init__(self, config, in_channels, out_channels, stride):
        super().__init__()
        if stride == 1:
            self.conv = nn.Conv1d(in_channels, out_channels, kernel_size=3, stride=1, padding=1)
        else:
            self.conv = nn.ConvTranspose1d(in_channels, out_channels, 2 * stride, stride, (stride + 1) // 2,
                                           1 if stride % 2 == 1 else 0, bias=False)
        self.res_units = nn.ModuleList([ResidualUnit(config, out_channels, out_channels, d) for d in config.block_dilations])

    def forward(self, x):
        x = self.conv(x)
        for unit in self.res_units:
            x = unit(x)
        return x


class SemanticDecoder(nn.Module):
    def __init__(self, config):
        super().__init__()
        size = config.semantic_hidden_size
        self.conv1 = nn.Conv1d(size, int(size * config.channel_ratios[0]), config.kernel_size, 1,
                               config.kernel_size // 2, bias=False)
        blocks = []
        for i, stride in enumerate(config.strides):
            in_channels = int(size * config.channel_ratios[i])
            out_channels = int(size * config.channel_ratios[i + 1]) if i < len(config.channel_ratios) - 1 else size
            blocks.append(SemanticDecoderBlock(config, in_channels, out_channels, stride))
        self.conv_blocks = nn.ModuleList(blocks)
        self.conv2 = nn.Conv1d(size, size, config.kernel_size, 1, config.kernel_size // 2, bias=False)

    def forward(self, x):
        x = self.conv1(x)
        for block in self.conv_blocks:
            x = block(x)
        return self.conv2(x)


@dataclass
class CodecOutput(ModelOutput):
    audio_codes: torch.LongTensor = None
    audio_values: torch.FloatTensor = None


class HiggsAudioV2TokenizerModel(PreTrainedModel):
    config_class = HiggsAudioV2TokenizerConfig
    base_model_prefix = "higgs_audio_v2_tokenizer"
    main_input_name = "input_values"
    _keys_to_ignore_on_load_unexpected = ["semantic_model.masked_spec_embed"]

    def __init__(self, config):
        super().__init__(config)
        self.pad = config.hop_length // 2
        acoustic = AutoModel.from_config(config.acoustic_model_config)
        self.acoustic_encoder = acoustic.encoder
        self.acoustic_decoder = acoustic.decoder
        for module in self.acoustic_decoder.modules():
            if isinstance(module, nn.ConvTranspose1d):
                stride = module.stride[0] if isinstance(module.stride, tuple) else module.stride
                module.output_padding = (stride % 2,)
        if hasattr(self.acoustic_decoder, "tanh") and isinstance(self.acoustic_decoder.tanh, nn.Tanh):
            self.acoustic_decoder.tanh = nn.Identity()
        self.encoder_semantic = SemanticEncoder(config)
        self.decoder_semantic = SemanticDecoder(config)
        self.semantic_model = AutoModel.from_config(config.semantic_model_config).eval()
        self.fc = nn.Linear(config.hidden_size, config.hidden_size)
        self.fc1 = nn.Linear(config.hidden_size, config.semantic_model_config.hidden_size)
        self.fc2 = nn.Linear(config.hidden_size, config.acoustic_model_config.hidden_size)
        self.quantizer = ResidualVectorQuantization(config)
        self.post_init()

    def _init_weights(self, module):
        pass  # inference only: every weight comes from the checkpoint

    def _acoustic_length(self, length):
        for layer in (m for m in self.acoustic_encoder.modules() if isinstance(m, nn.Conv1d)):
            length = _conv1d_output_length(layer, length)
        return length

    def _semantic_features(self, input_values):
        if self.config.sample_rate != self.config.semantic_sample_rate:
            input_values = torchaudio.functional.resample(input_values, self.config.sample_rate,
                                                          self.config.semantic_sample_rate)
        input_values = F.pad(input_values[:, 0, :], (160, 160))
        with torch.no_grad():
            hidden = self.semantic_model(input_values, output_hidden_states=True).hidden_states
        features = torch.stack([h.to(input_values.device) for h in hidden], dim=1).mean(dim=1)
        factor = self.config.semantic_downsample_factor
        return features[:, ::factor, :] if factor > 1 else features

    @torch.no_grad()
    def encode(self, input_values, bandwidth=None, return_dict=True):
        bandwidth = bandwidth or self.config.target_bandwidths[-1]
        semantic = self.encoder_semantic(self._semantic_features(input_values).detach().transpose(1, 2))
        if self._acoustic_length(input_values.shape[2]) != semantic.shape[2]:
            acoustic = self.acoustic_encoder(F.pad(input_values, (self.pad, self.pad)))
        else:
            acoustic = self.acoustic_encoder(input_values)
        embeddings = torch.cat([acoustic.to(semantic.device), semantic], dim=1)
        embeddings = self.fc(embeddings.transpose(1, 2)).transpose(1, 2)
        codes = self.quantizer.encode(embeddings, bandwidth).transpose(0, 1)
        return CodecOutput(audio_codes=codes) if return_dict else codes

    @torch.no_grad()
    def decode(self, audio_codes, return_dict=True):
        quantized = self.quantizer.decode(audio_codes.transpose(0, 1))
        values = self.acoustic_decoder(self.fc2(quantized.transpose(1, 2)).transpose(1, 2))
        return CodecOutput(audio_values=values) if return_dict else values
