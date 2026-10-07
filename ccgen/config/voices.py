# voices.py - dubbing voices for the speech engines and how a mode resolves to one
#
# OmniVoice and XTTS-v2 clone the original speaker, so each has one "voice" per language it can
# speak. Kokoro and Piper ship fixed voices, listed in small catalog snapshots bundled under
# ccgen/assets (Piper from rhasspy/piper-voices voices.json, Kokoro from hexgrad/Kokoro-82M
# VOICES.md; the files record their source URLs). Catalog rows outside the app's dubbing languages are skipped.
# Each Piper row also names its upstream MODEL_CARD ("card"), kept for provenance only.

import json
from dataclasses import dataclass
from typing import Optional

from ccgen.config.defaults import DubbingDefaults
from ccgen.utils.helpers import resource_path

ENGINE_OMNIVOICE = DubbingDefaults.MODE_OMNIVOICE
ENGINE_XTTS = DubbingDefaults.MODE_XTTS
ENGINE_KOKORO = DubbingDefaults.MODE_KOKORO
ENGINE_PIPER = DubbingDefaults.MODE_PIPER
ENGINES = (ENGINE_OMNIVOICE, ENGINE_XTTS, ENGINE_KOKORO, ENGINE_PIPER)
CLONING_ENGINES = frozenset({ENGINE_OMNIVOICE, ENGINE_XTTS})
ENGINE_LABELS = {
    ENGINE_OMNIVOICE: "OmniVoice", ENGINE_XTTS: "XTTS-v2", ENGINE_KOKORO: "Kokoro", ENGINE_PIPER: "Piper",
}

# OmniVoice language ids for every dubbing language (it knows 600+). Arabic is Standard Arabic,
# "arb"; OmniVoice's table has no plain "ar".
OMNIVOICE_LANGUAGES: dict[str, str] = {
    "ar": "arb", "de": "de", "en": "en", "es": "es", "fr": "fr", "hi": "hi", "ja": "ja", "ko": "ko",
    "pt": "pt", "ru": "ru", "tr": "tr", "ur": "ur", "zh": "zh",
}

# Languages XTTS-v2 was trained on, mapped to the codes its tokenizer expects.
XTTS_LANGUAGES: dict[str, str] = {
    "en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "pt": "pt", "pl": "pl",
    "tr": "tr", "ru": "ru", "nl": "nl", "cs": "cs", "ar": "ar", "zh": "zh-cn", "ja": "ja",
    "hu": "hu", "ko": "ko", "hi": "hi",
}
# The Kokoro catalog names French differently from the eSpeak voice Kokoro pronounces with;
# eSpeak rejects "fr" and needs this name instead.
_ESPEAK_LOCALES = {"fr": "fr-fr"}
# Japanese and Chinese stock voices need phonemizers the app doesn't ship: through eSpeak, which
# reads kanji and hanzi as "Japanese letter" and "Chinese letter", the benchmark heard almost
# nothing of Kokoro's right (Japanese: every line failed; Chinese: 80%), and Piper's need
# pyopenjtalk, or unicode_rbnf and a g2pW model downloaded on first use. Those languages are
# dubbed with voice cloning, which the benchmark heard almost as well as native speakers.
_CLONING_ONLY = frozenset({"ja", "zh"})
# Kokoro voice grades from VOICES.md, best first; "unrated" voices sort after graded ones.
_GRADE_ORDER = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F+", "F", "unrated"]

_PREFERRED_PIPER = {
    "ar": "ar_JO-kareem-medium",
    "de": "de_DE-thorsten-medium",
    "en": "en_US-lessac-medium",
    "es": "es_ES-davefx-medium",
    "fr": "fr_FR-siwis-medium",
    "hi": "hi_IN-pratham-medium",
    "pt": "pt_BR-faber-medium",
    "ru": "ru_RU-denis-medium",
    "tr": "tr_TR-dfki-medium",
    "ur": "ur_PK-aegis_female-medium",
}


@dataclass(frozen=True)
class VoiceOption:
    """One voice an engine can dub with."""

    engine: str
    voice_id: str
    language: str
    label: str
    # Piper: folder inside rhasspy/piper-voices. XTTS: tokenizer code. OmniVoice: language id.
    model_path: str = ""
    locale: str = ""
    approx_size_bytes: int = 0
    grade: str = ""

    @property
    def key(self) -> str:
        """Stable identifier used in settings and job configs, e.g. "piper:ur_PK-fasih-medium"."""
        return f"{self.engine}:{self.voice_id}"


def _load_catalogs() -> tuple[VoiceOption, ...]:
    """Read the bundled Piper and Kokoro catalogs, keeping the dubbing languages they can speak."""
    languages = {code for _, code in DubbingDefaults.LANGUAGES} - _CLONING_ONLY
    voices: list[VoiceOption] = []
    with open(resource_path("ccgen/assets/piper_voices.json"), encoding="utf-8") as fh:
        for row in json.load(fh)["voices"]:
            if row["language"] in languages:
                voices.append(VoiceOption(
                    engine=ENGINE_PIPER, voice_id=row["id"], language=row["language"],
                    label=row["label"], model_path=row["model_path"],
                    approx_size_bytes=row.get("approx_size_bytes", 0),
                ))
    with open(resource_path("ccgen/assets/kokoro_voices.json"), encoding="utf-8") as fh:
        rows = sorted(json.load(fh)["voices"], key=lambda r: _GRADE_ORDER.index(r.get("grade", "unrated")))
        for row in rows:
            if row["language"] in languages:
                grade = row.get("grade", "unrated")
                voices.append(VoiceOption(
                    engine=ENGINE_KOKORO, voice_id=row["id"], language=row["language"],
                    label=f"{row['label']} (grade {grade})" if grade != "unrated" else row["label"],
                    locale=_ESPEAK_LOCALES.get(row["locale"]) or row["locale"], grade=grade,
                ))
    return tuple(voices)


VOICES = _load_catalogs()


_CLONING_LANGUAGES = {ENGINE_OMNIVOICE: OMNIVOICE_LANGUAGES, ENGINE_XTTS: XTTS_LANGUAGES}


def cloning_voice(engine: str, language: str) -> VoiceOption:
    """The pseudo-voice that clones the original speaker in one language."""
    return VoiceOption(
        engine=engine, voice_id="clone", language=language,
        label="Clone the original speaker", model_path=_CLONING_LANGUAGES[engine][language],
    )


def xtts_voice(language: str) -> VoiceOption:
    """The cloning pseudo-voice for one XTTS language."""
    return cloning_voice(ENGINE_XTTS, language)


def engine_supports(engine: str, language: str) -> bool:
    """True when `engine` can speak `language`."""
    if engine in _CLONING_LANGUAGES:
        return language in _CLONING_LANGUAGES[engine]
    return any(v.engine == engine and v.language == language for v in VOICES)


def voices_for(engine: str, language: str) -> list[VoiceOption]:
    """Voices `engine` offers for `language`, best first."""
    if engine in _CLONING_LANGUAGES:
        return [cloning_voice(engine, language)] if engine_supports(engine, language) else []
    voices = [v for v in VOICES if v.engine == engine and v.language == language]
    preferred = _PREFERRED_PIPER.get(language) if engine == ENGINE_PIPER else None
    return sorted(voices, key=lambda v: v.voice_id != preferred)


def voice_by_key(key: str) -> Optional[VoiceOption]:
    """Look a Kokoro or Piper voice up by its key; None when the catalog has no such voice."""
    return next((v for v in VOICES if v.key == key), None)


def _unspoken(language: str, mode: str) -> str:
    """Why no voice can dub `language` in `mode`, and what would."""
    if mode in CLONING_ENGINES and engine_supports(mode, language):
        return (f"{ENGINE_LABELS[mode]} needs the original recording or a voice recording to clone: "
                f"no stock voice speaks '{language}'.")
    cloner = next((e for e in ENGINES if e in CLONING_ENGINES and engine_supports(e, language)), None)
    if cloner is not None:
        return f"{ENGINE_LABELS[mode]} can't speak '{language}'; choose voice cloning ({ENGINE_LABELS[cloner]})."
    return f"No dubbing voice speaks '{language}'."


def resolve_voice(
    language: str,
    mode: str,
    voice_key: str = DubbingDefaults.VOICE_AUTO,
    can_clone: bool = True,
) -> tuple[VoiceOption, Optional[str]]:
    """Choose the voice to dub `language` with, and a warning when it isn't the requested one.

    The requested mode wins whenever it can speak the language (and, for a cloning engine, a
    reference recording exists to clone). Otherwise the first stock-voice engine (Kokoro, then
    Piper) that speaks it is used; a fallback never switches to the other cloning engine, whose
    licence the user may not have accepted. Raises ValueError when no engine speaks the language
    or a named voice is for another one.
    """
    def usable(engine: str) -> bool:
        return engine_supports(engine, language) and (engine not in CLONING_ENGINES or can_clone)

    fallbacks = (e for e in ENGINES if e not in CLONING_ENGINES and usable(e))
    engine = mode if usable(mode) else next(fallbacks, None)
    if engine is None:
        raise ValueError(_unspoken(language, mode))
    warning = None
    if engine != mode:
        reason = "has no original voice to clone" if mode in CLONING_ENGINES and engine_supports(mode, language) \
            else f"can't speak '{language}'"
        warning = f"{ENGINE_LABELS[mode]} {reason}, so {ENGINE_LABELS[engine]} was used instead."
    if engine == mode and voice_key != DubbingDefaults.VOICE_AUTO and engine not in CLONING_ENGINES:
        voice = voice_by_key(voice_key)
        if voice is None or voice.engine != engine:
            raise ValueError(f"Unknown {ENGINE_LABELS[engine]} voice: {voice_key}.")
        if voice.language != language:
            raise ValueError(f"The voice {voice.label} speaks '{voice.language}', not '{language}'.")
        return voice, warning
    return voices_for(engine, language)[0], warning
