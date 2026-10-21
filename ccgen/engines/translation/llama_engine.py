# llama_engine.py - Hy-MT2 translation on llama.cpp
#
# Tencent's Hy-MT2 1.8B (Apache-2.0) is a small translation language model that translates every
# pair directly and is the most accurate here into Japanese, Korean, and Chinese (FLORES-200,
# scripts/eval). It runs as one 4-bit GGUF file on llama.cpp, using a CPU thread per physical
# core. Each sentence goes through the model's own prompt. Names and technical terms written in
# Latin letters are passed as a glossary that keeps them as written, since without it the model
# spells them in the target script ("GitHub" came out in Urdu letters in testing).

import logging
import os
import re
from typing import Any, Callable, Optional

from ccgen.config.translation_models import ENGINE_HYMT, HYMT_LANGUAGES, HYMT_MODEL, route
from ccgen.core import Segment, TranslatedSegment
from ccgen.engines.model_cache import ModelCache
from ccgen.engines.translation.base import TranslationEngine
from ccgen.engines.translation.model_files import ensure_gguf
from ccgen.utils.callbacks import JobCancelled, emit_progress, emit_segment, emit_status

_log = logging.getLogger(__name__)

_models: ModelCache[Any] = ModelCache("Hy-MT2")
_CONTEXT_TOKENS = 2048
# Targets written in Latin letters keep names as they are without a glossary.
_LATIN_TARGETS = frozenset({"de", "en", "es", "fr", "pt", "tr"})
# Names and terms a translation keeps as written: CamelCase and ALL-CAPS words, and URLs.
_TERM_RE = re.compile(r"https?://\S+|\b[A-Z][a-z]+[A-Z]\w*\b|\b[A-Z]{2,}\w*\b")
# The model's Chinese prompt is used whenever Chinese is involved, its English one otherwise.
_CHINESE_NAMES = {
    "ar": "阿拉伯语", "de": "德语", "en": "英语", "es": "西班牙语", "fr": "法语", "hi": "印地语", "ja": "日语",
    "ko": "韩语", "pt": "葡萄牙语", "ru": "俄语", "tr": "土耳其语", "ur": "乌尔都语", "zh": "中文",
}


class LlamaEngine(TranslationEngine):
    """Translates every language pair directly with Hy-MT2 1.8B."""

    def __init__(self, source_lang: str, target_lang: str) -> None:
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._llm: Any = None

    def set_pair(self, source: str, target: str) -> None:
        """Change languages; the loaded model serves every pair."""
        self._source_lang = source
        self._target_lang = target

    def ensure_model(
        self,
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Download the model on first use, then load it."""
        try:
            route(ENGINE_HYMT, self._source_lang, self._target_lang)  # raises for a language it can't name
            path = ensure_gguf(HYMT_MODEL, progress_cb, progress_num_cb)
            self._llm = _models.get_or_load(path, lambda: _load(path))
            emit_status(progress_cb, "Hy-MT2 1.8B ready on CPU.")
        except (ValueError, JobCancelled):
            raise
        except Exception as e:
            _log.error("Translation model setup failed: %r", e, exc_info=True)
            raise RuntimeError(f"Translation model setup failed: {e}") from e

    def translate_segments(
        self,
        segments: list[Segment],
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
        segment_cb: Optional[Callable[[TranslatedSegment], None]] = None,
    ) -> list[TranslatedSegment]:
        """Translate sentence by sentence, streaming each result as it is ready."""
        if self._llm is None:
            raise RuntimeError("Call ensure_model() before translate_segments().")
        results: list[TranslatedSegment] = []
        for seg in segments:
            text = seg["text"].strip()
            result = TranslatedSegment(
                id=seg["id"], start=seg["start"], end=seg["end"], original=text,
                translated=self._translate(text) if text else "", language=self._target_lang,
            )
            results.append(result)
            emit_segment(segment_cb, result)
            emit_progress(progress_num_cb, len(results), len(segments))
        return results

    def _translate(self, text: str) -> str:
        """One sentence through the model, greedily decoded."""
        reply = self._llm.create_chat_completion(
            [{"role": "user", "content": prompt(text, self._source_lang, self._target_lang)}],
            temperature=0.0, max_tokens=min(_CONTEXT_TOKENS // 2, 64 + 8 * len(text)),
        )
        return str(reply["choices"][0]["message"]["content"]).strip()


def prompt(text: str, source: str, target: str) -> str:
    """Hy-MT2's translation prompt, with a glossary that keeps Latin-script terms as written."""
    terms = sorted(set(_TERM_RE.findall(text))) if target not in _LATIN_TARGETS else []
    if "zh" in (source, target):
        glossary = "".join(f"{term} 翻译成 {term}\n" for term in terms)
        head = f"参考下面的翻译：\n{glossary}" if terms else ""
        return f"{head}将以下文本翻译为{_CHINESE_NAMES[target]}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
    glossary = "".join(f"{term} translates to {term}\n" for term in terms)
    head = f"Reference the following translations:\n{glossary}\n" if terms else ""
    return (f"{head}Translate the following text into {HYMT_LANGUAGES[target]}. Note that you should only "
            f"output the translated result without any additional explanation:\n\n{text}")


def _load(path: str) -> Any:
    """Open the GGUF model with a thread per physical CPU core."""
    import psutil
    from llama_cpp import Llama

    threads = psutil.cpu_count(logical=False) or os.cpu_count() or 4
    return Llama(path, n_ctx=_CONTEXT_TOKENS, n_threads=threads, verbose=False)
