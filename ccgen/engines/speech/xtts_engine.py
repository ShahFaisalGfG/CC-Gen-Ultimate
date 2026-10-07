# xtts_engine.py - XTTS-v2 voice cloning: speaks translated text in each original speaker's voice
#
# The model needs a few seconds of a speaker's voice to imitate it. Reference audio arrives as
# arrays cut from the source media (see ccgen.core.speakers), so nothing is written to disk and
# the torchaudio/torchcodec file loaders are never used.

import logging
import os
from typing import Any, Optional

import numpy as np
import torch
import torch.nn.functional as F
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts

from ccgen.engines.devices import Accelerator, first_working, torch_accelerators
from ccgen.engines.model_cache import ModelCache
from ccgen.engines.speech.base import (
    REFERENCE_RATE,
    CloningEngine,
    ProgressCb,
    StatusCb,
    finish_sentence,
    split_for_speech,
)
from ccgen.engines.speech.numbers import spell_numbers, spells_numbers
from ccgen.engines.speech.voice_files import ensure_xtts
from ccgen.utils.callbacks import emit_status

_log = logging.getLogger(__name__)

_models: ModelCache[tuple[Xtts, str]] = ModelCache("XTTS-v2")
_WARMUP_TEXT = "Hello."
_DEFAULT_CHAR_LIMIT = 200
_PIECE_GAP_S = 0.12

# Runaway guard. XTTS-v2 picks speech tokens by sampling and sometimes keeps talking past the
# text (babble), most often on very short lines. Normal speech runs about 0.09 s per character
# of text, so a take far longer than that is spoken again with cooler sampling; if every take
# runs on, the shortest is decoded only up to a plausible length, which keeps its real words.
_SECONDS_PER_CHAR = 0.09
_MIN_EXPECTED_S = 0.8
_RUNAWAY_FACTOR = 1.8
_RUNAWAY_MARGIN_S = 0.5
_RETRY_TEMPERATURES = (0.5, 0.3)
_CAP_FACTOR = 1.3


class XttsEngine(CloningEngine):
    """Clones each registered speaker and speaks text in their voice."""

    def load(self, status_cb: StatusCb = None, progress_cb: ProgressCb = None) -> None:
        """Download the checkpoint on first use, then move it to the first device that can hold it."""
        def loader() -> tuple[Xtts, str]:
            emit_status(status_cb, "Preparing XTTS-v2 voice cloning...")
            checkpoint_dir = ensure_xtts(progress_cb)
            emit_status(status_cb, "Loading XTTS-v2...")
            config = XttsConfig()
            config.load_json(os.path.join(checkpoint_dir, "config.json"))
            model = Xtts.init_from_config(config)
            model.load_checkpoint(config, checkpoint_dir=checkpoint_dir, eval=True)
            model, accelerator = first_working(torch_accelerators(self._device_preference), lambda a: _place(model, a))
            return model, accelerator.label

        self._model, self.device_label = _models.get_or_load(self._device_preference, loader)
        # The tokenizer's language code (zh-cn for Chinese).
        self._language = self.voice.model_path
        self._speakers: dict[int, tuple[Any, Any]] = {}
        # The last line's GPT output per piece, so retime() only reruns the fast audio decoder.
        self._last_line: Optional[tuple[str, int, list[Any]]] = None

    @property
    def output_rate(self) -> int:
        """Sample rate of synthesized speech."""
        return int(self._model.config.audio.output_sample_rate)

    @torch.inference_mode()
    def embed(self, audio: np.ndarray) -> np.ndarray:
        """Speaker embedding of one clip, used to tell speakers apart."""
        tensor = torch.from_numpy(audio.astype(np.float32)).unsqueeze(0).to(self._model.device)
        return self._model.get_speaker_embedding(tensor, REFERENCE_RATE).flatten().cpu().numpy()

    @torch.inference_mode()
    def set_speakers(self, references: dict[int, list[np.ndarray]]) -> None:
        """Compute each speaker's conditioning from their reference clips."""
        config = self._model.config
        max_samples = REFERENCE_RATE * config.max_ref_len
        self._speakers = {}
        for speaker, clips in references.items():
            tensors = [
                torch.from_numpy(clip[:max_samples].astype(np.float32)).unsqueeze(0).to(self._model.device)
                for clip in clips
            ]
            gpt_latent = self._model.get_gpt_cond_latents(
                torch.cat(tensors, dim=-1), REFERENCE_RATE,
                length=config.gpt_cond_len, chunk_length=config.gpt_cond_chunk_len,
            )
            embedding = torch.stack([self._model.get_speaker_embedding(t, REFERENCE_RATE) for t in tensors]).mean(dim=0)
            self._speakers[speaker] = (gpt_latent, embedding)

    @torch.inference_mode()
    def synthesize(self, text: str, speed: float = 1.0, speaker: int = 0) -> tuple[np.ndarray, int]:
        """Speak `text` in the registered speaker's cloned voice."""
        if speaker not in self._speakers:
            raise RuntimeError(f"No reference voice was registered for speaker {speaker}.")
        gpt_latent, embedding = self._speakers[speaker]
        spoken = finish_sentence(text, self.voice.language)
        spoken = spell_numbers(spoken, self._language) if spells_numbers(self._language) else spoken
        # XTTS cuts audio short past a per-language length, and its own splitter loads spaCy
        # pipelines (Japanese needs SudachiPy), so long lines are split here instead.
        limit = self._model.tokenizer.char_limits.get(self._language.split("-")[0], _DEFAULT_CHAR_LIMIT)
        self.last_line_capped = False
        takes = [self._speak_piece(piece, gpt_latent, embedding, speed) for piece in split_for_speech(spoken, limit)]
        if speed == 1.0:
            self._last_line = (text, speaker, [latents for _, latents in takes])
        return self._join([wav for wav, _ in takes]), self.output_rate

    def _speak_piece(self, piece: str, gpt_latent: Any, embedding: Any, speed: float) -> tuple[np.ndarray, Any]:
        """Speak one piece, guarding against runaway takes; return its audio and GPT latents."""
        expected_s = max(_MIN_EXPECTED_S, len(piece) * _SECONDS_PER_CHAR) / speed
        longest = int((expected_s * _RUNAWAY_FACTOR + _RUNAWAY_MARGIN_S) * self.output_rate)
        shortest: Optional[tuple[np.ndarray, Any]] = None
        for temperature in (None, *_RETRY_TEMPERATURES):
            options: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
            out = self._model.inference(piece, self._language, gpt_latent, embedding, speed=speed, **options)
            take = (np.asarray(out["wav"], dtype=np.float32), torch.from_numpy(out["gpt_latents"]))
            if take[0].size <= longest:
                return take
            if shortest is None or take[0].size < shortest[0].size:
                shortest = take
        assert shortest is not None
        wav, latents = shortest
        # The latents are what was decoded, so audio length maps to latent frames one to one.
        frames = max(1, int(latents.shape[1] * expected_s * _CAP_FACTOR * self.output_rate / wav.size))
        latents = latents[:, :frames]
        wav = self._model.hifigan_decoder(latents.to(self._model.device), g=embedding).cpu().squeeze().numpy()
        _log.info("XTTS-v2 kept talking past %d characters of text; cut the take to %.1f s", len(piece), wav.size / self.output_rate)
        self.last_line_capped = True
        return wav.astype(np.float32), latents

    @torch.inference_mode()
    def retime(self, text: str, speed: float, speaker: int = 0) -> tuple[np.ndarray, int]:
        """Re-speak the last line faster by stretching its GPT output and decoding it again.

        This is what XTTS does for `speed` anyway, but without rerunning the autoregressive GPT,
        the slow part of synthesis, so fitting a line into its time costs a fraction of a line.
        """
        if self._last_line is None or self._last_line[:2] != (text, speaker):
            return self.synthesize(text, speed, speaker)
        _, embedding = self._speakers[speaker]
        pieces = []
        for latents in self._last_line[2]:
            stretched = F.interpolate(latents.transpose(1, 2), scale_factor=1.0 / speed, mode="linear").transpose(1, 2)
            wav = self._model.hifigan_decoder(stretched.to(self._model.device), g=embedding)
            pieces.append(wav.cpu().squeeze().numpy().astype(np.float32))
        return self._join(pieces), self.output_rate

    def _join(self, pieces: list[np.ndarray]) -> np.ndarray:
        """Concatenate the audio of a line's pieces with a short pause between them."""
        gap = np.zeros(int(_PIECE_GAP_S * self.output_rate), dtype=np.float32)
        joined = [part for piece in pieces for part in (piece, gap)][:-1]
        return np.concatenate(joined) if joined else np.zeros(0, dtype=np.float32)


def _place(model: Xtts, accelerator: Accelerator) -> Xtts:
    """Move the model to a device and, for a GPU, prove it can speak there."""
    model.to(accelerator.handle)
    if accelerator.is_gpu:
        with torch.inference_mode():
            noise = (torch.rand(1, REFERENCE_RATE, device=accelerator.handle) - 0.5) * 0.1
            latent = model.get_gpt_cond_latents(noise, REFERENCE_RATE)
            embedding = model.get_speaker_embedding(noise, REFERENCE_RATE)
            model.inference(_WARMUP_TEXT, "en", latent, embedding)
    return model
