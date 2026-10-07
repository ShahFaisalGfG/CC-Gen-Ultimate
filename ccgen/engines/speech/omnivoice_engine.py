# omnivoice_engine.py - OmniVoice voice cloning: native pronunciation in each original speaker's voice
#
# OmniVoice (k2-fsa) reads 600+ languages, Urdu among them, and imitates a speaker from a few
# seconds of their voice plus the transcript of those seconds. Its inference code is vendored in
# ./omnivoice (that package lists the changes made to run on the app's transformers). Reference
# clips arrive as arrays cut from the source media; their transcripts come from the app's own
# Whisper, because the dub's cues hold the translated text, not what the speaker said. OmniVoice
# has no speaker encoder, so speakers are told apart with WavLM speaker vectors instead.

import logging
from typing import Any, Optional

import numpy as np
import torch

from ccgen.engines.devices import Accelerator, first_working, torch_accelerators
from ccgen.engines.model_cache import ModelCache
from ccgen.engines.speech.base import REFERENCE_RATE, CloningEngine, ProgressCb, StatusCb, finish_sentence
from ccgen.engines.speech.line_check import load_transcriber
from ccgen.engines.speech.numbers import spell_numbers, spells_numbers
from ccgen.engines.speech.voice_files import ensure_omnivoice, ensure_speaker_vectors
from ccgen.utils.callbacks import emit_status

_log = logging.getLogger(__name__)

_models: ModelCache[tuple[Any, str]] = ModelCache("OmniVoice")
_vectors: ModelCache[tuple[Any, Any]] = ModelCache("Speaker vectors")

# Denoising steps per line. 32 is the model's own setting; 8 measured the same intelligibility
# and speaker similarity on Urdu (CER 0.03, similarity 0.98) at a quarter of the time.
QUALITY_STEPS = 32
FAST_STEPS = 8
# OmniVoice clones best from 3-10 s of speech; a speaker's clips are joined up to this length.
_REFERENCE_MAX_S = 10.0
_CLIP_GAP_S = 0.2
# The voice prompt's transcript must match its audio word for word: a word whose sound is cut
# off is one OmniVoice finishes before each line, heard as a short "hiccup" and a pause (7 of 12
# lines of an Urdu test dub; none once the prompt held only whole words). So each clip is cut to
# the words Whisper heard whole in it: words within this far of a clip's edge may be cut off and
# are left out, the kept words keep a little room around them, and the prompt ends in silence.
_EDGE_S = 0.1
_WORD_ROOM_S = (0.05, 0.08)
# A clip with less than this left to add is skipped rather than ending the prompt mid-phrase.
_MIN_PIECE_S = 1.0
_FADE_S = 0.02
_TAIL_S = 0.3
_WHISPER_RATE = 16000
_WARMUP_TEXT = "Hello."


class OmniVoiceEngine(CloningEngine):
    """Clones each registered speaker with OmniVoice and speaks text in their voice."""

    def __init__(self, voice: Any, device: str, steps: int = QUALITY_STEPS) -> None:
        super().__init__(voice, device)
        self.steps = steps

    def load(self, status_cb: StatusCb = None, progress_cb: ProgressCb = None) -> None:
        """Download the model on first use, then move it to the first device that runs it."""
        from ccgen.engines.speech.omnivoice.model import OmniVoice, OmniVoiceGenerationConfig

        def loader() -> tuple[Any, str]:
            emit_status(status_cb, "Preparing OmniVoice voice cloning...")
            folder = ensure_omnivoice(progress_cb)
            emit_status(status_cb, "Loading OmniVoice...")
            model = OmniVoice.from_pretrained(folder, dtype=torch.float32)
            model, accelerator = first_working(torch_accelerators(self._device_preference), lambda a: _place(model, a))
            return model, accelerator.label

        self._model, self.device_label = _models.get_or_load(self._device_preference, loader)
        self._config = OmniVoiceGenerationConfig(num_step=self.steps)
        self._prompts: dict[int, Any] = {}

    @property
    def output_rate(self) -> int:
        """Sample rate of synthesized speech."""
        return int(self._model.sampling_rate)

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """WavLM speaker vector of one clip, used to tell speakers apart."""
        extractor, model = _vectors.get_or_load("wavlm", _load_vectors)
        inputs = extractor(_resample(audio, REFERENCE_RATE, _WHISPER_RATE), sampling_rate=_WHISPER_RATE,
                           return_tensors="pt")
        with torch.inference_mode():
            return model(**inputs).embeddings[0].numpy()

    def set_speakers(self, references: dict[int, list[np.ndarray]]) -> None:
        """Build each speaker's voice prompt from their clips and what they say in them."""
        transcriber = load_transcriber()
        self._prompts = {}
        for speaker, clips in references.items():
            joined, text = _reference(transcriber, clips)
            if not text:
                # Music or noise: without a transcript the prompt would mislead the model, so
                # this speaker gets OmniVoice's own neutral voice instead.
                _log.warning("No speech found in speaker %d's reference audio; using a neutral voice", speaker)
                self._prompts[speaker] = None
                continue
            waveform = torch.from_numpy(joined.astype(np.float32))
            self._prompts[speaker] = self._model.create_voice_clone_prompt((waveform, REFERENCE_RATE), ref_text=text)

    def natural_seconds(self, text: str, speaker: int = 0) -> Optional[float]:
        """How long OmniVoice will speak `text` at normal speed, estimated before synthesis."""
        prompt = self._prompts.get(speaker)
        ref_text = prompt.ref_text if prompt is not None else None
        ref_tokens = prompt.ref_audio_tokens.shape[-1] if prompt is not None else None
        tokens = self._model._estimate_target_tokens(self._spoken(text), ref_text, ref_tokens)
        return tokens / self._model.audio_tokenizer.config.frame_rate

    @torch.inference_mode()
    def synthesize(self, text: str, speed: float = 1.0, speaker: int = 0) -> tuple[np.ndarray, int]:
        """Speak `text` in the registered speaker's cloned voice, `speed` times faster than normal."""
        if speaker not in self._prompts:
            raise RuntimeError(f"No reference voice was registered for speaker {speaker}.")
        audio = self._model.generate(
            text=self._spoken(text), language=self.voice.model_path, voice_clone_prompt=self._prompts[speaker],
            speed=speed if speed != 1.0 else None, generation_config=self._config,
        )[0]
        return np.asarray(audio, dtype=np.float32), self.output_rate

    def _spoken(self, text: str) -> str:
        """The text as it is read: a finished sentence, with digits spelled where needed."""
        spoken = finish_sentence(text, self.voice.language)
        return spell_numbers(spoken, self.voice.language) if spells_numbers(self.voice.language) else spoken


def _place(model: Any, accelerator: Accelerator) -> Any:
    """Move the model to a device (half precision on a GPU) and prove it can speak there."""
    model.to(accelerator.handle)
    if accelerator.is_gpu:
        model.half()
        model.audio_tokenizer.float()  # the audio codec stays in full precision, as upstream runs it
        with torch.inference_mode():
            model.generate(text=_WARMUP_TEXT, language="en", num_step=2)
    return model


def _load_vectors() -> tuple[Any, Any]:
    """The WavLM speaker-verification model and its feature extractor, on the CPU."""
    from transformers import AutoFeatureExtractor, WavLMForXVector

    folder = ensure_speaker_vectors()
    return AutoFeatureExtractor.from_pretrained(folder), WavLMForXVector.from_pretrained(folder).eval()


def _reference(engine: Any, clips: list[np.ndarray]) -> tuple[np.ndarray, str]:
    """A speaker's voice prompt and its transcript: the whole words of their clips, joined with
    short pauses up to the length OmniVoice clones best from, then a moment of silence."""
    gap = np.zeros(int(_CLIP_GAP_S * REFERENCE_RATE), dtype=np.float32)
    room = int(_REFERENCE_MAX_S * REFERENCE_RATE)
    parts: list[np.ndarray] = []
    texts: list[str] = []
    for clip in clips:
        used = sum(part.size for part in parts) + (gap.size if parts else 0)
        audio, text = _whole_words(engine, clip, (room - used) / REFERENCE_RATE)
        if not text or (parts and audio.size < _MIN_PIECE_S * REFERENCE_RATE):
            continue
        if parts:
            parts.append(gap)
        parts.append(audio)
        texts.append(text)
    if not parts:
        return np.zeros(0, dtype=np.float32), ""
    parts.append(np.zeros(int(_TAIL_S * REFERENCE_RATE), dtype=np.float32))
    return np.concatenate(parts), " ".join(texts)


def _whole_words(engine: Any, clip: np.ndarray, limit: float) -> tuple[np.ndarray, str]:
    """The part of a clip holding the words Whisper heard whole in it, at most `limit` seconds
    long, and those words ("" when none fit)."""
    if limit <= 0:
        return np.zeros(0, dtype=np.float32), ""
    segments = engine.transcribe(_resample(clip, REFERENCE_RATE, _WHISPER_RATE), language=None, vad_filter=False)
    length = clip.size / REFERENCE_RATE
    words = [w for s in segments for w in s.get("words", []) if w["start"] > _EDGE_S and w["end"] < length - _EDGE_S]
    start = max(0.0, words[0]["start"] - _WORD_ROOM_S[0]) if words else 0.0
    words = [w for w in words if w["end"] + _WORD_ROOM_S[1] - start <= limit]
    if not words:
        return np.zeros(0, dtype=np.float32), ""
    end = min(length, words[-1]["end"] + _WORD_ROOM_S[1])
    audio = clip[int(start * REFERENCE_RATE): int(end * REFERENCE_RATE)].astype(np.float32)
    fade = min(int(_FADE_S * REFERENCE_RATE), audio.size // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        audio[:fade] *= ramp
        audio[-fade:] *= ramp[::-1]
    # Whisper's words carry their own leading spaces (none in Chinese or Japanese).
    return audio, "".join(w["word"] for w in words).strip()


def _resample(audio: np.ndarray, rate: int, target: int) -> np.ndarray:
    """Band-limited resampling with torchaudio (already loaded with torch)."""
    import torchaudio

    tensor = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
    return torchaudio.functional.resample(tensor, rate, target).numpy()
