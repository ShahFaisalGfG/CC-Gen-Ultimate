# capabilities.py - which language and script pairs each engine can handle
#
# Kept free of engine imports (torch, transformers, argos) so config validation, the API, and
# the UI controllers can answer "is this supported?" without loading any model code.

import os
import re
from typing import Optional

from ccgen.config.defaults import LanguageOptions, ModelRepos, TransliterationDefaults
from ccgen.config.translation_models import ENGINE_ARGOS, ENGINE_HYMT, HYMT_MODEL, models_for

_SCHEME_CODES = frozenset(code for _, code in TransliterationDefaults.SCHEMES)
# Punjabi has no direct neural model; the neural engine pivots it through Devanagari to reach
# the Hindi -> Urdu model.
_REKHTA_SOURCES = frozenset({"hi", "pa"})
_KNOWN_LANGUAGES = frozenset(
    code for _, code in LanguageOptions.TRANSCRIPTION + LanguageOptions.TRANSLATION_TARGETS if code
)
# Argos publishes most pairs only to and from English, which the translator pivots through.
PIVOT_LANGUAGE = "en"
_LANGUAGE_SUFFIX = re.compile(r"_([a-z]{2}(?:-[a-z]{2})?)$")


def transliteration_supported(engine: str, source: str, target: str) -> bool:
    """Return True when `engine` can convert text written in `source` script to `target`."""
    if source == target:
        return False
    if engine == TransliterationDefaults.ENGINE_RULE:
        return source in _SCHEME_CODES and target in _SCHEME_CODES
    if engine == TransliterationDefaults.ENGINE_NEURAL:
        return neural_model_key(source, target) is not None
    return False


def neural_model_key(source: str, target: str) -> Optional[str]:
    """Return the asset key of the neural model serving a script pair, or None."""
    if (source, target) in ModelRepos.M2M100:
        return f"{source}-{target}"
    if source in _REKHTA_SOURCES and target == "ur":
        return "hi-ur"
    return None


def translation_asset_ids(source: str, target: str, engine: str = ENGINE_ARGOS) -> list[str]:
    """Manage Models ids of what `engine` needs to translate source→target ("" source: not known yet).

    Argos needs a package per direction (via English when needed). NLLB, MADLAD, and Hy-MT2 need
    their one model whatever the pair; OPUS-MT needs the models on its route, and with the source
    not known yet, the model from English into the target.
    """
    if source == target or not target:
        return []
    if engine == ENGINE_HYMT:
        return [f"translation:{HYMT_MODEL.key}"]
    if engine == ENGINE_ARGOS:
        if not source:
            return []
        if PIVOT_LANGUAGE in (source, target):
            return [f"translation:{source}-{target}"]
        return [f"translation:{source}-{PIVOT_LANGUAGE}", f"translation:{PIVOT_LANGUAGE}-{target}"]
    source = source or PIVOT_LANGUAGE
    if source == target:
        return []
    try:
        return [f"translation:{model.key}" for model in models_for(engine, source, target)]
    except ValueError:
        return []


def language_from_filename(path: str) -> str:
    """Return the language code in a `_xx` file-name suffix (`movie_ur.srt` -> "ur"), or ""."""
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    match = _LANGUAGE_SUFFIX.search(stem)
    if match and match.group(1) in _KNOWN_LANGUAGES:
        return match.group(1)
    return ""
