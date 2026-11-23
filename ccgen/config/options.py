# options.py - every choice the task settings offer, as plain lists for the API and the command line
#
# GET /options fills the app's pickers from option_lists(), and `ccgen options` prints the same
# lists, so a script or an AI agent sees exactly the choices the app shows. setting_choices() names
# the values each saved setting accepts, which `ccgen settings set` checks before saving.

from typing import Any

from ccgen.config.defaults import (
    AUTO,
    ComputeDefaults,
    DubbingDefaults,
    LanguageOptions,
    LoggingDefaults,
    ModelDefaults,
    OutputDefaults,
    TransliterationDefaults,
)
from ccgen.config.licences import TERMS
from ccgen.config.profiles import PROFILE_CHOICES
from ccgen.config.translation_models import ENGINES as TRANSLATION_ENGINES
from ccgen.config.voices import VOICES

THEMES = ("system", "light", "dark")


def option_lists() -> dict[str, list]:
    """Every option list the task settings use, as {label, code} items (and voices with their engine)."""
    return {
        "models": ModelDefaults.SUPPORTED_MODELS,
        "languages": _as_items(LanguageOptions.TRANSCRIPTION),
        "translation_targets": _as_items(LanguageOptions.TRANSLATION_TARGETS),
        "translation_engines": [{"label": e.label, "code": e.key, "hint": e.hint} for e in TRANSLATION_ENGINES],
        "translit_schemes": _as_items(TransliterationDefaults.SCHEMES),
        "translit_engines": _as_items(TransliterationDefaults.ENGINES),
        "dub_modes": [{"label": label, "code": code, "hint": hint} for label, code, hint in DubbingDefaults.MODES],
        "dub_languages": _as_items(DubbingDefaults.LANGUAGES),
        "dub_qualities": [{"label": label, "code": code, "hint": hint}
                          for label, code, hint in DubbingDefaults.QUALITIES],
        "dub_speakers": _as_items(DubbingDefaults.SPEAKERS),
        "voices": [
            {"key": v.key, "engine": v.engine, "language": v.language, "label": v.label} for v in VOICES
        ],
        "devices": _as_items(ComputeDefaults.DEVICES),
        "compute_types": ComputeDefaults.SUPPORTED_COMPUTE_TYPES,
        "subtitle_formats": list(OutputDefaults.FORMATS),
        "profiles": [{"label": p.label, "code": p.key, "hint": p.hint} for p in PROFILE_CHOICES],
        "licences": [{"code": t.key, "label": t.title, "url": t.url} for t in TERMS.values()],
    }


def setting_choices() -> dict[str, tuple[Any, ...]]:
    """The values a saved setting accepts, by its dot-separated key (settings not listed take any value
    of their type, within setting_ranges())."""
    targets = tuple(code for _, code in LanguageOptions.TRANSLATION_TARGETS)
    spoken = tuple(code for _, code in LanguageOptions.TRANSCRIPTION)
    schemes = tuple(code for _, code in TransliterationDefaults.SCHEMES)
    return {
        "model.name": (AUTO, *ModelDefaults.SUPPORTED_MODELS),
        "model.device": tuple(ComputeDefaults.SUPPORTED_DEVICES),
        "model.compute_type": tuple(ComputeDefaults.SUPPORTED_COMPUTE_TYPES),
        "transcription.language": spoken,
        "translation.source_lang": (AUTO, *targets),
        "translation.target_lang": targets,
        "translation.engine": tuple(e.key for e in TRANSLATION_ENGINES),
        "transliteration.source": (TransliterationDefaults.SOURCE_AUTO, *schemes),
        "transliteration.target": schemes,
        "transliteration.engine": tuple(code for _, code in TransliterationDefaults.ENGINES),
        "dubbing.mode": tuple(code for _, code, _ in DubbingDefaults.MODES),
        "dubbing.speakers": tuple(code for _, code in DubbingDefaults.SPEAKERS),
        "dubbing.output": tuple(code for _, code in DubbingDefaults.OUTPUTS),
        "dubbing.device": tuple(code for _, code in DubbingDefaults.DEVICES),
        "dubbing.quality": tuple(code for _, code, _ in DubbingDefaults.QUALITIES),
        "performance.profile": ("", *(p.key for p in PROFILE_CHOICES)),
        "logging.log_level": tuple(LoggingDefaults.SUPPORTED_LOG_LEVELS),
        "ui.theme": THEMES,
    }


def setting_ranges() -> dict[str, tuple[float, float]]:
    """The lowest and highest value of the numeric settings that have limits."""
    return {
        "output.max_line_length": OutputDefaults.MAX_LINE_LENGTH_RANGE,
        "output.max_lines": OutputDefaults.MAX_LINES_RANGE,
        "dubbing.max_speedup": DubbingDefaults.MAX_SPEEDUP_RANGE,
        "transcription.beam_size": (1, 20),
    }


def _as_items(pairs: list) -> list[dict[str, str]]:
    """Convert (label, code) tuples into {label, code} dicts for JSON responses."""
    return [{"label": label, "code": code or ""} for label, code in pairs]

