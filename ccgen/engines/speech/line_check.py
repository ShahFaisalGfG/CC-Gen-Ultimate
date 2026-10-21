# line_check.py - hear each dubbed line back and catch the ones that came out garbled
#
# Voice cloning samples its speech, so now and then a line comes out as the wrong syllables or
# keeps talking past its text. Listeners notice those lines first: a dub with one garbled line
# in ten was judged unusable even though its average was fine (see scripts/eval/calibrate.py).
# Whisper transcribes every synthesized line, and a line whose transcript is far from its text,
# or much longer than it, is spoken again; the best take is kept.

import logging
import re
import unicodedata
from typing import Any

import numpy as np

_log = logging.getLogger(__name__)

# Whisper models tried, in order, for transcribing reference voices, where every word counts; the
# first one already downloaded is used, otherwise "small" is fetched.
_TRANSCRIBERS = ("large-v3-turbo", "large-v3", "medium", "small")
_FALLBACK_TRANSCRIBER = "small"
# Hearing lines back only has to catch garbled speech, which "small" does in every language at a
# quarter of large-v3-turbo's time on a CPU.
CHECK_TRANSCRIBER = "small"
# A line fails when more than half its characters are wrong (no native recording in the
# benchmark came close), or when the transcript runs on by more than 30% (babble).
FAILED_CER = 0.5
RUN_ON = 0.3
_WHISPER_RATE = 16000
# Languages written without spaces between words.
_UNSPACED = frozenset({"ja", "zh"})
# Languages written in Latin script; in the others, names and terms kept in Latin letters
# (GitHub, ML Ops) may be heard back in the native script, so the line check skips them.
_LATIN_LANGUAGES = frozenset({"de", "en", "es", "fr", "pt", "tr"})
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'.-]*")
# Arabic-script letters that Whisper and subtitle text spell differently (Urdu and Arabic).
_ARABIC_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ە": "ہ", "ۀ": "ہ", "ٔ": None, "ـ": None})


def load_transcriber(model: str = "") -> Any:
    """A loaded Whisper engine: `model`, or the most accurate model already on disk."""
    from ccgen.engines.captions.whisper_engine import WhisperEngine
    from ccgen.utils.model_status import scan_hf_cache, whisper_cached

    if not model:
        cache = scan_hf_cache()
        model = next((m for m in _TRANSCRIBERS if whisper_cached(m, cache)), _FALLBACK_TRANSCRIBER)
    engine = WhisperEngine(model_name=model)
    engine.load()
    return engine


def normalize(text: str, language: str) -> str:
    """Text reduced to what speech carries: no case, punctuation, diacritics, or spacing."""
    text = unicodedata.normalize("NFKC", text).lower().translate(_ARABIC_FOLD)
    kept = []
    for ch in unicodedata.normalize("NFD", text):
        category = unicodedata.category(ch)
        if category == "Mn" and language not in ("hi", "ko", "ja"):
            continue  # Arabic-script vowel marks and Latin accents are written inconsistently
        kept.append(" " if category[0] in "PSZ" else ch)
    text = unicodedata.normalize("NFC", "".join(kept))
    return re.sub(r"\s+", "" if language in _UNSPACED else " ", text).strip()


def character_error_rate(transcript: str, text: str, language: str) -> float:
    """Character error rate of a transcript against the text that was spoken (spaces ignored)."""
    hyp = normalize(transcript, language).replace(" ", "")
    ref = normalize(text, language).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(hyp, ref) / len(ref)


def run_on(transcript: str, text: str, language: str) -> float:
    """How much longer the transcript is than the text, as a share of the text (0 when shorter)."""
    hyp = normalize(transcript, language).replace(" ", "")
    ref = normalize(text, language).replace(" ", "")
    return max(0, len(hyp) - len(ref)) / max(1, len(ref))


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


class LineChecker:
    """Scores synthesized lines by how well Whisper understands them."""

    def __init__(self, transcriber: Any, language: str) -> None:
        self._transcriber = transcriber
        self._language = language

    def score(self, audio: np.ndarray, rate: int, text: str) -> float:
        """0 for a line heard exactly as written; FAILED_CER or more for a garbled one.

        Speech that runs past its text counts as failed even when its start is right.
        """
        import torch
        import torchaudio

        clip = torchaudio.functional.resample(torch.from_numpy(np.ascontiguousarray(audio, np.float32)), rate,
                                              _WHISPER_RATE).numpy()
        segments = self._transcriber.transcribe(clip, language=self._language, vad_filter=False)
        transcript = " ".join(segment["text"].strip() for segment in segments)
        error = _line_error(transcript, text, self._language)
        _log.debug("Line check %.2f: %r heard as %r", error, text, transcript)
        return error


def _line_error(transcript: str, text: str, language: str) -> float:
    """How badly a transcript misses its line; FAILED_CER or more for garbled or run-on speech.

    In a language not written in Latin letters, names and terms kept in Latin letters (Abhishek,
    ML Ops) are heard back in the native script, so they are left out of the comparison: only
    how much of the rest of the line was heard counts, and the speech may run longer by about
    their length.
    """
    names = _LATIN_WORD.findall(text) if language not in _LATIN_LANGUAGES else []
    if not names:
        error = character_error_rate(transcript, text, language)
        return max(error, FAILED_CER) if run_on(transcript, text, language) > RUN_ON else error
    rest = normalize(_LATIN_WORD.sub(" ", text), language).replace(" ", "")
    heard = normalize(_LATIN_WORD.sub(" ", transcript), language).replace(" ", "")
    if not rest:
        return 0.0  # the line is all names: nothing left that can be checked
    error = 1.0 - _common_length(heard, rest) / len(rest)
    allowance = sum(len(name) for name in names) * 1.5
    if (len(heard) - len(rest) - allowance) / len(rest) > RUN_ON:
        error = max(error, FAILED_CER)
    return error


def _common_length(a: str, b: str) -> int:
    """Length of the longest common subsequence of two strings."""
    previous = [0] * (len(b) + 1)
    for ca in a:
        current = [0]
        for j, cb in enumerate(b, 1):
            current.append(previous[j - 1] + 1 if ca == cb else max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]
