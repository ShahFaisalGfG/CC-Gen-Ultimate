# metrics.py - scores for translations and synthesized speech
#
# Translation: chrF against professional references (character n-grams, so it works the same
# for Urdu, Chinese, and German), plus the app's own meaning score and the length ratio.
#
# Speech, per clip: the character error rate when a strong recogniser (Whisper
# large-v3-turbo) transcribes the clip in the target language, how much speech the transcript
# has beyond the text (babble), the speaking rate, and the cosine similarity of WavLM speaker
# vectors of the clip and the voice that was cloned. calibrate.py checks these against native
# speech and the dub listeners rejected; DNSMOS and Whisper's language confidence were tried
# there and dropped, since neither told the two apart (DNSMOS even rated the dub higher).

import re
from collections import Counter
from typing import Optional

import numpy as np

# The app's own line check scores dubbed lines the same way, so the benchmark reuses it.
from ccgen.engines.speech.line_check import character_error_rate as cer
from ccgen.engines.speech.line_check import normalize
from ccgen.engines.speech.line_check import run_on as extra_speech

ASR_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
SPEAKER_MODEL = "microsoft/wavlm-base-plus-sv"
RATE_16K = 16000


def chrf(hypotheses: list[str], references: list[str], order: int = 6, beta: float = 2.0) -> float:
    """Corpus chrF (sacreBLEU's default chrF: character 6-grams, beta 2, spaces ignored)."""
    totals = np.zeros((order, 3))
    for hyp, ref in zip(hypotheses, references):
        hyp, ref = re.sub(r"\s+", "", hyp), re.sub(r"\s+", "", ref)
        for n in range(1, order + 1):
            h = Counter(hyp[i:i + n] for i in range(len(hyp) - n + 1))
            r = Counter(ref[i:i + n] for i in range(len(ref) - n + 1))
            totals[n - 1] += (sum(h.values()), sum(r.values()), sum((h & r).values()))
    # Precision and recall are averaged over the orders both sides have, then combined.
    present = [(m / h, m / r) for h, r, m in totals if h > 0 and r > 0]
    if not present:
        return 0.0
    prec = sum(p for p, _ in present) / len(present)
    rec = sum(r for _, r in present) / len(present)
    factor = beta ** 2
    return 100 * (1 + factor) * prec * rec / (factor * prec + rec) if prec + rec else 0.0


def resample(audio: np.ndarray, rate: int, target: int = RATE_16K) -> np.ndarray:
    """Band-limited resampling to `target` Hz."""
    if rate == target:
        return audio.astype(np.float32)
    import librosa

    return librosa.resample(audio.astype(np.float32), orig_sr=rate, target_sr=target).astype(np.float32)


class Recognizer:
    """Whisper large-v3-turbo transcription on the CPU."""

    def __init__(self, model: str = ASR_MODEL) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray, rate: int, language: str) -> str:
        """The transcript of a clip, decoded as `language`."""
        segments, _ = self._model.transcribe(
            resample(audio, rate), language=language, beam_size=5,
            condition_on_previous_text=False, vad_filter=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class SpeakerSimilarity:
    """Cosine similarity of WavLM x-vectors (above about 0.86 usually means the same speaker)."""

    def __init__(self, model: str = SPEAKER_MODEL) -> None:
        from transformers import AutoFeatureExtractor, WavLMForXVector

        self._extractor = AutoFeatureExtractor.from_pretrained(model)
        self._model = WavLMForXVector.from_pretrained(model).eval()

    def vector(self, audio: np.ndarray, rate: int) -> np.ndarray:
        """Unit-length speaker vector of a clip."""
        import torch

        inputs = self._extractor(resample(audio, rate), sampling_rate=RATE_16K, return_tensors="pt")
        with torch.inference_mode():
            embedding = self._model(**inputs).embeddings[0].numpy()
        return embedding / max(float(np.linalg.norm(embedding)), 1e-9)

    def score(self, audio: np.ndarray, rate: int, reference: np.ndarray) -> float:
        """Similarity of a clip to a reference speaker vector."""
        return float(np.dot(self.vector(audio, rate), reference))


def summarize(values: list[float]) -> Optional[dict[str, float]]:
    """Mean, median, and spread of a metric over clips."""
    if not values:
        return None
    array = np.asarray(values, dtype=np.float64)
    return {"mean": float(array.mean()), "median": float(np.median(array)), "p90": float(np.percentile(array, 90)),
            "min": float(array.min()), "max": float(array.max()), "n": int(array.size)}


__all__ = ["Recognizer", "SpeakerSimilarity", "cer", "chrf", "extra_speech", "normalize", "summarize"]
