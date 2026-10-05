# translation - translation engine registry

from typing import Optional

from ccgen.config.defaults import TranslationDefaults
from ccgen.config.translation_models import DEFAULT_ENGINE, ENGINE_ARGOS, ENGINE_KEYS
from ccgen.engines.translation.argos_engine import ArgosEngine
from ccgen.engines.translation.base import TranslationEngine
from ccgen.engines.translation.fidelity import MeaningCheck


def create_engine(
    name: str = DEFAULT_ENGINE,
    source_lang: str = TranslationDefaults.DEFAULT_SOURCE_LANG,
    target_lang: str = TranslationDefaults.DEFAULT_TARGET_LANG,
    meaning: Optional[MeaningCheck] = None,
) -> TranslationEngine:
    """Instantiate the named translation engine.

    `meaning` lets the CTranslate2 engines pick, among several candidates, the one closest in
    meaning to the original. Raises ValueError when the engine name is not registered.
    """
    if name not in ENGINE_KEYS:
        raise ValueError(f"Unknown translation engine: '{name}'. Supported: {list(ENGINE_KEYS)}")
    if name == ENGINE_ARGOS:
        return ArgosEngine(source_lang=source_lang, target_lang=target_lang)
    # Imported here: CTranslate2 and its model loaders are only needed when one is chosen.
    from ccgen.engines.translation.ct2_engine import Ct2Engine

    return Ct2Engine(name, source_lang, target_lang, meaning)


__all__ = ["TranslationEngine", "ArgosEngine", "MeaningCheck", "create_engine"]
