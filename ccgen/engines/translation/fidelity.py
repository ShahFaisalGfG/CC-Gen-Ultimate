# fidelity.py - check that a translation keeps the meaning of the original
#
# A small multilingual sentence-embedding model (paraphrase-multilingual-MiniLM-L12-v2, Apache
# 2.0, 8-bit ONNX) places a sentence and its translation close together when they say the same
# thing, in any of its 50+ languages. Embedding similarity catches invented or dropped content
# well but ignores language, so an untranslated copy would score high: candidates are also
# penalised for staying in the wrong script, for an implausible length, and for losing names and
# technical terms (GitHub, ML Ops, URLs) that a translation should carry over unchanged.

import logging
import os
import re
from typing import Any, Callable, Optional

import numpy as np

from ccgen.engines.model_cache import ModelCache
from ccgen.engines.translation.model_files import ensure_meaning_model

_log = logging.getLogger(__name__)

_models: ModelCache[tuple[Any, Any]] = ModelCache("Meaning check")
_MAX_TOKENS = 256
# Targets written in Latin letters; any other target should come out mostly in its own script.
_LATIN_TARGETS = frozenset({"de", "en", "es", "fr", "pt", "tr"})
# Terms a translation keeps as written: CamelCase or ALL-CAPS words, URLs, and email addresses.
_TERM_RE = re.compile(r"https?://\S+|\S+@\S+\.\S+|\b[A-Z][a-z]+[A-Z]\w*\b|\b[A-Z]{2,}\b")
_WRONG_SCRIPT_PENALTY = 0.3
_LENGTH_PENALTY = 0.15
_LOST_TERM_PENALTY = 0.05
_LENGTH_RATIO = (0.35, 3.0)
# Below this adjusted similarity a line is reported as possibly not matching the original.
# Tuned on English-Urdu course subtitles: OPUS-MT's faithful lines scored 0.69-0.98, while the
# Argos lines that drifted ("follow the course in order" -> "follow your own path") scored
# 0.54-0.59. A single mistranslated word in an otherwise faithful sentence still scores high;
# the better models, not this check, are what fix those.
DOUBT_THRESHOLD = 0.62


class MeaningCheck:
    """Scores how well translations keep the meaning of their source sentences."""

    def __init__(self) -> None:
        self._session: Any = None
        self._tokenizer: Any = None

    def ensure(self, status_cb: Optional[Callable[[str], None]] = None,
               progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
        """Download the model on first use and load it."""
        folder = ensure_meaning_model(status_cb, progress_cb)
        self._session, self._tokenizer = _models.get_or_load(folder, lambda: _load(folder))

    def scores(self, sources: list[str], translations: list[str], target: str) -> list[float]:
        """Adjusted similarity of each translation to its source (higher keeps more meaning)."""
        if not sources:
            return []
        similarity = (self._embed(sources) * self._embed(translations)).sum(axis=1)
        return [float(s) - _penalty(src, out, target) for s, src, out in zip(similarity, sources, translations)]

    def choose(self, sources: list[str], candidates: list[list[str]], target: str) -> list[tuple[str, float]]:
        """For each source, the candidate that keeps its meaning best, with its score."""
        flat_sources = [src for src, options in zip(sources, candidates) for _ in options]
        flat = [option for options in candidates for option in options]
        flat_scores = self.scores(flat_sources, flat, target)
        chosen: list[tuple[str, float]] = []
        start = 0
        for options in candidates:
            scored = list(zip(options, flat_scores[start:start + len(options)]))
            start += len(options)
            chosen.append(max(scored, key=lambda pair: pair[1]) if scored else ("", 0.0))
        return chosen

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Unit-length sentence embeddings (mean of the token vectors)."""
        if self._session is None:
            raise RuntimeError("Call ensure() before scoring translations.")
        encoded = self._tokenizer.encode_batch([t or " " for t in texts])
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in {i.name for i in self._session.get_inputs()}:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        pooled = (hidden * mask[..., None]).sum(axis=1) / np.maximum(mask.sum(axis=1, keepdims=True), 1)
        return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9)


def _load(folder: str) -> tuple[Any, Any]:
    """Open the ONNX model on the CPU and its tokenizer."""
    import onnxruntime
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(os.path.join(folder, "tokenizer.json"))
    tokenizer.enable_truncation(_MAX_TOKENS)
    tokenizer.enable_padding()
    model = os.path.join(folder, "onnx", "model_quint8_avx2.onnx")
    session = onnxruntime.InferenceSession(model, providers=["CPUExecutionProvider"])
    return session, tokenizer


def _penalty(source: str, translation: str, target: str) -> float:
    """What to subtract from a candidate's similarity for being the wrong kind of output."""
    penalty = 0.0
    letters = [ch for ch in translation if ch.isalpha()]
    if target not in _LATIN_TARGETS and letters:
        latin = sum(1 for ch in letters if ch.isascii())
        if latin / len(letters) > 0.5:
            penalty += _WRONG_SCRIPT_PENALTY
    ratio = len(translation) / max(1, len(source))
    if not _LENGTH_RATIO[0] <= ratio <= _LENGTH_RATIO[1]:
        penalty += _LENGTH_PENALTY
    lost = sum(1 for term in set(_TERM_RE.findall(source)) if term not in translation)
    return penalty + lost * _LOST_TERM_PENALTY
