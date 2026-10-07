# omnivoice_worker.py - OmniVoice (k2-fsa, CC-BY-NC weights) zero-shot voice cloning on the CPU
#
# Runs in its own environment, because the omnivoice package needs transformers 5.3 or newer
# (the app ships 4.57); README.md shows how to create it. It covers 600+ languages, Urdu among
# them, and clones a voice from a short reference clip and its transcript.
#
# OMNIVOICE_STEPS sets the denoising steps (default 32). OMNIVOICE_BACKEND=onnx runs the
# transformer as the dynamic-INT8 ONNX graph from gaber/OmniVoice-ONNX-CPU-INT8 (with its FP32
# audio encoder and vocoder) on ONNX Runtime, the route the app itself could take; the loader
# follows that repo's use_onnx.py.

import inspect
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import run_jobs  # noqa: E402

MODEL = "k2-fsa/OmniVoice"
REVISION = "c5fdb5ccb189668d56333f77ba2629f4cd7535f4"
ONNX_REPO = "gaber/OmniVoice-ONNX-CPU-INT8"
ONNX_REVISION = "efddec1c39169c79e57eb65f1a7b650d0906a182"
ONNX_FILES = ["backbone.int8.onnx", "encoder.fp32.onnx", "vocoder.fp32.onnx*", "config.json", "tokenizer.json",
              "tokenizer_config.json", "chat_template.jinja", "preprocessor_config.json"]
OUTPUT_RATE = 24000
# OmniVoice language ids are ISO 639-3 where the two-letter code is ambiguous (Arabic is
# Standard Arabic, "arb"); the others match our codes.
LANGUAGE_IDS = {"ar": "arb"}


def _load_torch():
    from omnivoice import OmniVoice

    return OmniVoice.from_pretrained(MODEL, revision=REVISION, device_map="cpu", dtype=torch.float32)


def _load_onnx(threads: int):
    """OmniVoice's sampling loop with the transformer and audio codec replaced by ONNX graphs."""
    import onnxruntime
    from huggingface_hub import snapshot_download
    from omnivoice import OmniVoice
    from omnivoice.models.omnivoice import OmniVoiceConfig
    from omnivoice.utils.duration import RuleDurationEstimator
    from transformers import AutoTokenizer

    folder = Path(snapshot_download(ONNX_REPO, revision=ONNX_REVISION, allow_patterns=ONNX_FILES))
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1

    def session(name: str):
        return onnxruntime.InferenceSession(str(folder / name), options, providers=["CPUExecutionProvider"])

    backbone, encoder, vocoder = session("backbone.int8.onnx"), session("encoder.fp32.onnx"), session("vocoder.fp32.onnx")
    pre = json.loads((folder / "preprocessor_config.json").read_text())

    class AudioCodec:
        device = torch.device("cpu")
        config = SimpleNamespace(hop_length=pre["hop_length"], frame_rate=pre["sampling_rate"] // pre["hop_length"])

        def encode(self, wav):
            codes = encoder.run(None, {"wav": wav.cpu().numpy().astype(np.float32)})[0]
            return SimpleNamespace(audio_codes=torch.from_numpy(codes))

        def decode(self, codes):
            out = vocoder.run(None, {"audio_codes": codes.cpu().numpy()})[0]
            return SimpleNamespace(audio_values=torch.from_numpy(out))

    class StubLLM(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(_attn_implementation="sdpa")

    model = OmniVoice(OmniVoiceConfig.from_pretrained(folder), llm=StubLLM()).eval()
    model.text_tokenizer = AutoTokenizer.from_pretrained(folder)
    model.sampling_rate = pre["sampling_rate"]
    model.duration_estimator = RuleDurationEstimator()
    model.audio_tokenizer = AudioCodec()

    def forward(input_ids: Any, audio_mask: Any, attention_mask: Any, **_: Any) -> SimpleNamespace:
        out = backbone.run(None, {"input_ids": input_ids.numpy(), "audio_mask": audio_mask.numpy(),
                                  "attention_mask": attention_mask.numpy()})[0]
        return SimpleNamespace(logits=torch.from_numpy(out))

    model.forward = forward
    return model


def main() -> None:
    from omnivoice.models.omnivoice import OmniVoiceGenerationConfig

    threads = os.cpu_count() or 4
    torch.set_num_threads(threads)
    model = _load_onnx(threads) if os.environ.get("OMNIVOICE_BACKEND") == "onnx" else _load_torch()
    takes_language = "language" in inspect.signature(model.generate).parameters
    # Denoising steps (the model's default is 32); fewer steps run proportionally faster.
    config = OmniVoiceGenerationConfig(num_step=int(os.environ.get("OMNIVOICE_STEPS", "32")))

    def speak(job: dict) -> tuple:
        language = LANGUAGE_IDS.get(job["language"], job["language"])
        options = {"language": language} if takes_language else {}
        audio = model.generate(text=job["text"], ref_audio=job["ref_audio"], ref_text=job["ref_text"],
                               generation_config=config, **options)
        return audio[0], OUTPUT_RATE

    run_jobs(speak)


if __name__ == "__main__":
    main()
