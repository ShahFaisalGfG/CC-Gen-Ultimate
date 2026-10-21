# whisper_engine.py - faster-whisper wrapper producing word-timestamped segments

import logging
import os
from typing import Callable, Iterator, Optional

import numpy as np
from faster_whisper import WhisperModel

from ccgen.config.defaults import AUTO, AudioDefaults, ComputeDefaults, TranscriptionDefaults
from ccgen.config.profiles import whisper_model
from ccgen.core import Segment, WordToken
from ccgen.engines.captions.base import CaptionEngine
from ccgen.engines.devices import ct2_gpu_compute_type, ct2_open
from ccgen.engines.model_cache import ModelCache
from ccgen.utils.callbacks import JobCancelled, emit_progress, emit_segment, emit_status
from ccgen.utils.download_progress import download_progress

_log = logging.getLogger(__name__)

_models: ModelCache[WhisperModel] = ModelCache("Whisper")
# One second of silence: enough to run the encoder once and prove the GPU libraries load.
_CUDA_PROBE_SAMPLES = 16000


def resolve_compute(device: str, compute_type: str) -> tuple[str, str]:
    """Resolve "auto" device/compute type values into concrete CTranslate2 settings: the GPU's
    fastest type (float32 on older GPUs) or 8-bit on the CPU."""
    gpu_type = None if device == "cpu" else ct2_gpu_compute_type()
    if device == ComputeDefaults.DEVICE_AUTO:
        device = "cuda" if gpu_type else "cpu"
    if compute_type == ComputeDefaults.COMPUTE_AUTO:
        compute_type = (gpu_type or "float32") if device == "cuda" else "int8"
    return device, compute_type


class WhisperEngine(CaptionEngine):
    """Wraps faster-whisper; loads the model once and transcribes on demand."""

    def __init__(
        self,
        model_name: str = AUTO,
        device: str = ComputeDefaults.DEFAULT_DEVICE,
        compute_type: str = ComputeDefaults.DEFAULT_COMPUTE_TYPE,
    ) -> None:
        self._model_name = whisper_model(model_name, "")
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None

    def load(
        self,
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Load (and download if needed) the Whisper model, reusing a cached instance.

        With device "auto", a GPU that fails to initialise (for example missing CUDA runtime
        libraries) falls back to the CPU instead of failing the job, and an older GPU that runs
        only in float32 is timed against the CPU and used only when faster.
        """
        try:
            emit_status(progress_cb, f"Loading model '{self._model_name}'...")
            if self._device == ComputeDefaults.DEVICE_AUTO:
                self._model, device, compute_type = ct2_open(
                    f"whisper:{self._model_name}",
                    lambda d, c: self._load_cached(d, c, progress_num_cb),
                    lambda model: model.detect_language(np.zeros(_CUDA_PROBE_SAMPLES, dtype=np.float32)),
                    self._compute_type,
                )
            else:
                device, compute_type = resolve_compute(self._device, self._compute_type)
                self._model = self._load_cached(device, compute_type, progress_num_cb)
            emit_status(progress_cb, f"Model ready ({'GPU' if device == 'cuda' else 'CPU'}).")
            _log.info("Whisper model ready: %s on %s/%s", self._model_name, device, compute_type)
        except JobCancelled:
            raise
        except Exception as e:
            _log.error("Model load failed (%s): %r", self._model_name, e, exc_info=True)
            raise RuntimeError(f"Model load failed ({self._model_name}): {e}") from e

    def transcribe(
        self,
        audio: str | np.ndarray,
        language: Optional[str] = TranscriptionDefaults.DEFAULT_LANGUAGE,
        beam_size: int = TranscriptionDefaults.BEAM_SIZE,
        vad_filter: bool = TranscriptionDefaults.VAD_FILTER,
        progress_cb: Optional[Callable[[str], None]] = None,
        segment_cb: Optional[Callable[["Segment"], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Segment]:
        """Transcribe a media file path or 16 kHz mono samples into word-timestamped segments.

        Raises RuntimeError when the model is not loaded or transcription fails, and lets
        JobCancelled from a callback propagate so a cancelled job stops between segments.
        """
        try:
            if self._model is None:
                raise RuntimeError("Call load() before transcribe().")
            if isinstance(audio, str):
                if not os.path.isfile(audio):
                    raise FileNotFoundError(f"Audio file not found: {audio}")
                source = os.path.basename(audio)
            else:
                source = f"{audio.size / AudioDefaults.SAMPLE_RATE:.1f} s of audio"
            _log.info(
                "Transcribing: %s (lang=%s, beam=%d, vad=%s)", source, language, beam_size, vad_filter,
            )
            segments = list(
                self._iter_segments(audio, language, beam_size, vad_filter, segment_cb, progress_num_cb)
            )
            _log.info("Transcription complete: %d segments", len(segments))
            return segments
        except (RuntimeError, FileNotFoundError, JobCancelled):
            raise
        except Exception as e:
            _log.error("Transcription failed: %r", e, exc_info=True)
            raise RuntimeError(f"Transcription failed: {e}") from e

    def is_loaded(self) -> bool:
        """Return True when a model is currently held by this engine."""
        return self._model is not None

    def unload(self) -> None:
        """Drop this engine's reference to the model (the shared cache may still hold it)."""
        self._model = None

    def _load_cached(
        self,
        device: str,
        compute_type: str,
        progress_num_cb: Optional[Callable[[int, int], None]],
    ) -> WhisperModel:
        """Return the cached model for this configuration, loading it on a cache miss."""

        def loader() -> WhisperModel:
            with download_progress(progress_num_cb):
                model = WhisperModel(self._model_name, device=device, compute_type=compute_type)
            if device == "cuda":
                # Model construction succeeds even when cuBLAS/cuDNN are missing; the first
                # encoder pass is what fails, so probe once here instead of mid-transcription.
                model.detect_language(np.zeros(_CUDA_PROBE_SAMPLES, dtype=np.float32))
            return model

        return _models.get_or_load((self._model_name, device, compute_type), loader)

    def _iter_segments(
        self,
        audio: str | np.ndarray,
        language: Optional[str],
        beam_size: int,
        vad_filter: bool,
        segment_cb: Optional[Callable[["Segment"], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
    ) -> Iterator[Segment]:
        """Iterate faster-whisper output, yield typed Segment dicts, and fire segment_cb per segment."""
        vad_params = {"min_silence_duration_ms": TranscriptionDefaults.VAD_MIN_SILENCE_MS}
        segments, info = self._model.transcribe(  # type: ignore[union-attr]
            audio,
            language=language,
            beam_size=beam_size,
            word_timestamps=TranscriptionDefaults.WORD_TIMESTAMPS,
            vad_filter=vad_filter,
            vad_parameters=vad_params,
            condition_on_previous_text=TranscriptionDefaults.CONDITION_ON_PREVIOUS_TEXT,
            hallucination_silence_threshold=TranscriptionDefaults.HALLUCINATION_SILENCE_S,
            language_detection_segments=TranscriptionDefaults.LANGUAGE_DETECTION_SEGMENTS,
        )
        detected = info.language if language is None else language
        duration_ms = int(info.duration * 1000)
        for idx, seg in enumerate(segments):
            emit_progress(progress_num_cb, int(seg.end * 1000), duration_ms)
            words: list[WordToken] = []
            if seg.words:
                words = [WordToken(word=w.word, start=w.start, end=w.end) for w in seg.words]
            built = Segment(
                id=idx,
                start=seg.start,
                end=seg.end,
                text=seg.text,
                words=words,
                language=detected,
            )
            emit_segment(segment_cb, built)
            yield built
