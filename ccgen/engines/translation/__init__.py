# translation - translation engine registry

from typing import Callable, Optional

from ccgen.config.defaults import TranslationDefaults
from ccgen.config.profiles import translation_engine
from ccgen.config.translation_models import DEFAULT_ENGINE, ENGINE_ARGOS, ENGINE_AUTO, ENGINE_HYMT, ENGINE_KEYS
from ccgen.core import Segment, TranslatedSegment
from ccgen.engines.translation.argos_engine import ArgosEngine
from ccgen.engines.translation.base import TranslationEngine
from ccgen.engines.translation.fidelity import MeaningCheck


def create_engine(
    name: str = DEFAULT_ENGINE,
    source_lang: str = TranslationDefaults.DEFAULT_SOURCE_LANG,
    target_lang: str = TranslationDefaults.DEFAULT_TARGET_LANG,
    meaning: Optional[MeaningCheck] = None,
    profile: str = "",
    for_speech: bool = False,
) -> TranslationEngine:
    """Instantiate the named translation engine.

    `meaning` lets the CTranslate2 engines pick, among several candidates, the one closest in
    meaning to the original, and with `for_speech` (the text will be dubbed) the one that takes
    as long to say. "auto" picks the engine for each language pair from the performance
    `profile`. Raises ValueError when the engine name is not registered.
    """
    if name not in ENGINE_KEYS:
        raise ValueError(f"Unknown translation engine: '{name}'. Supported: {list(ENGINE_KEYS)}")
    if name == ENGINE_AUTO:
        return AutoEngine(profile, source_lang, target_lang, meaning, for_speech)
    if name == ENGINE_ARGOS:
        return ArgosEngine(source_lang=source_lang, target_lang=target_lang)
    if name == ENGINE_HYMT:
        # Imported here: llama.cpp is only loaded when Hy-MT2 is chosen.
        from ccgen.engines.translation.llama_engine import LlamaEngine

        return LlamaEngine(source_lang, target_lang)
    # Imported here: CTranslate2 and its model loaders are only needed when one is chosen.
    from ccgen.engines.translation.ct2_engine import Ct2Engine

    return Ct2Engine(name, source_lang, target_lang, meaning, for_speech)


class AutoEngine(TranslationEngine):
    """Translates with the engine the performance profile picks for the current language pair.

    The pair is often known only at run time (a detected source language), so the engine is
    chosen when the models are prepared, after the last set_pair().
    """

    def __init__(
        self, profile: str, source_lang: str, target_lang: str, meaning: Optional[MeaningCheck], for_speech: bool = False,
    ) -> None:
        self._profile = profile
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._meaning = meaning
        self._for_speech = for_speech
        self._engine: Optional[TranslationEngine] = None
        self.resolved = ""

    def set_pair(self, source: str, target: str) -> None:
        """Change languages; the engine is chosen again on the next ensure_model()."""
        self._source_lang = source
        self._target_lang = target
        self._engine = None

    def ensure_model(
        self,
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Choose the engine for the pair, then download and load its models."""
        self.resolved = translation_engine(ENGINE_AUTO, self._profile, self._source_lang, self._target_lang)
        self._engine = create_engine(self.resolved, self._source_lang, self._target_lang, self._meaning,
                                     for_speech=self._for_speech)
        self._engine.ensure_model(progress_cb, progress_num_cb)

    def translate_segments(
        self,
        segments: list[Segment],
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
        segment_cb: Optional[Callable[[TranslatedSegment], None]] = None,
    ) -> list[TranslatedSegment]:
        """Translate with the chosen engine."""
        if self._engine is None:
            raise RuntimeError("Call ensure_model() before translate_segments().")
        return self._engine.translate_segments(segments, progress_cb, progress_num_cb, segment_cb)


__all__ = ["TranslationEngine", "ArgosEngine", "AutoEngine", "MeaningCheck", "create_engine"]
