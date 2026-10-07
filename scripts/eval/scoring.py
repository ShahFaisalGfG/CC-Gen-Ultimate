# scoring.py - score synthesized or recorded speech clips with the calibrated speech metrics
#
# Calibration (calibrate.py) on the dub listeners rejected showed that averages hide what a
# listener hears: one garbled line ruins a dub. So a group of clips is judged by its mean CER,
# its share of failed lines (CER above 0.5, which no native recording reached), its share of
# babble (speech well beyond the text), and its speaking rate against native speakers of the
# same language (the rejected dub was rushed: 0.068 s per character against 0.087 natively).

import time
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from metrics import Recognizer, SpeakerSimilarity, cer, extra_speech, summarize

FAILED_CER = 0.5
BABBLE_EXTRA = 0.3


@dataclass
class ClipScore:
    """All metrics for one clip."""

    text: str
    transcript: str
    cer: float
    extra_speech: float
    speaker_similarity: Optional[float]
    seconds: float
    seconds_per_char: float
    synthesis_seconds: Optional[float] = None


class Scorer:
    """Loads the recogniser and the speaker model once and scores clips with them."""

    def __init__(self) -> None:
        self.recognizer = Recognizer()
        self.speakers = SpeakerSimilarity()

    def score(self, audio: np.ndarray, rate: int, text: str, language: str,
              reference: Optional[np.ndarray] = None, synthesis_seconds: Optional[float] = None) -> ClipScore:
        """Score one clip of `text` spoken in `language`; `reference` is the cloned voice's vector."""
        audio = _trim(audio, rate)
        transcript = self.recognizer.transcribe(audio, rate, language)
        seconds = audio.size / rate
        return ClipScore(
            text=text, transcript=transcript, cer=cer(transcript, text, language),
            extra_speech=extra_speech(transcript, text, language),
            speaker_similarity=None if reference is None else self.speakers.score(audio, rate, reference),
            seconds=seconds, seconds_per_char=seconds / max(1, len(text)), synthesis_seconds=synthesis_seconds,
        )


def summary(scores: list[ClipScore], native_seconds_per_char: Optional[float] = None) -> dict:
    """Group metrics: CER spread, failed and babble shares, speaking rate, similarity, speed."""
    if not scores:
        return {}
    out: dict = {name: summarize([v for s in scores if (v := getattr(s, name)) is not None])
                 for name in ("cer", "speaker_similarity", "seconds_per_char", "synthesis_seconds")}
    out["failed_rate"] = sum(s.cer > FAILED_CER for s in scores) / len(scores)
    out["babble_rate"] = sum(s.extra_speech > BABBLE_EXTRA for s in scores) / len(scores)
    if native_seconds_per_char:
        # Above 1 the voice speaks faster than native speakers read the same kind of text.
        out["rate_vs_native"] = native_seconds_per_char / out["seconds_per_char"]["median"]
    out["clips"] = len(scores)
    return out


def clip_rows(scores: list[ClipScore]) -> list[dict]:
    """Plain dicts for the JSON report."""
    return [asdict(s) for s in scores]


def _trim(audio: np.ndarray, rate: int, below_peak_db: float = 35.0) -> np.ndarray:
    """Cut leading and trailing silence so durations compare speech, not padding."""
    frame = max(1, int(0.02 * rate))
    frames = audio[: audio.size // frame * frame].reshape(-1, frame)
    if frames.size == 0:
        return audio
    level = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    loud = np.flatnonzero(level > level.max() - below_peak_db)
    if loud.size == 0:
        return audio
    start = max(0, loud[0] - 2) * frame
    end = min(frames.shape[0], loud[-1] + 3) * frame
    return audio[start:end]


class Timer:
    """Wall-clock seconds of a block."""

    def __enter__(self) -> "Timer":
        self.started = time.perf_counter()
        self.seconds = 0.0
        return self

    def __exit__(self, *_: object) -> None:
        self.seconds = time.perf_counter() - self.started
