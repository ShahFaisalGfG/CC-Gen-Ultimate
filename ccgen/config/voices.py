# voices.py - dubbing voices for the three speech engines and how a mode resolves to one
#
# XTTS-v2 clones the original speaker, so it has one "voice" per language it can speak. Kokoro
# and Piper ship fixed voices, listed in small catalog snapshots bundled under ccgen/assets
# (Piper from rhasspy/piper-voices voices.json, Kokoro from hexgrad/Kokoro-82M VOICES.md; the
# files record their source URLs). Catalog rows outside the app's dubbing languages are skipped.
# Each Piper row also names its upstream MODEL_CARD ("card"), kept for provenance only.

import json
from dataclasses import dataclass
from typing import Optional

from ccgen.config.defaults import DubbingDefaults
from ccgen.utils.helpers import resource_path

ENGINE_XTTS = DubbingDefaults.MODE_XTTS
ENGINE_KOKORO = DubbingDefaults.MODE_KOKORO
ENGINE_PIPER = DubbingDefaults.MODE_PIPER
ENGINES = (ENGINE_XTTS, ENGINE_KOKORO, ENGINE_PIPER)
ENGINE_LABELS = {ENGINE_XTTS: "XTTS-v2", ENGINE_KOKORO: "Kokoro", ENGINE_PIPER: "Piper"}

# Languages XTTS-v2 was trained on, mapped to the codes its tokenizer expects.
XTTS_LANGUAGES: dict[str, str] = {
    "en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "pt": "pt", "pl": "pl",
    "tr": "tr", "ru": "ru", "nl": "nl", "cs": "cs", "ar": "ar", "zh": "zh-cn", "ja": "ja",
    "hu": "hu", "ko": "ko", "hi": "hi",
}
# Languages XTTS-v2 can still speak by reading them in another language's script. Spoken Urdu
# and Hindi share their sounds, so Urdu lines written in Devanagari are read as Urdu.
XTTS_SCRIPT_BRIDGE: dict[str, str] = {"ur": "hi"}
_SCRIPT_NAMES = {"hi": "Hindi"}
# The Kokoro catalog names some languages differently from the eSpeak voices Kokoro
# pronounces with; eSpeak rejects "fr" and "zh" and needs these names instead.
_ESPEAK_LOCALES = {"fr": "fr-fr", "zh": "cmn"}
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
    # Piper: folder inside rhasspy/piper-voices. Kokoro: espeak locale. XTTS: tokenizer code.
    model_path: str = ""
    locale: str = ""
    approx_size_bytes: int = 0
    grade: str = ""
    # XTTS only: the language whose script the lines are rewritten in before speaking (see
    # XTTS_SCRIPT_BRIDGE), or "" when the voice speaks its language directly.
    bridge: str = ""

    @property
    def key(self) -> str:
        """Stable identifier used in settings and job configs, e.g. "piper:ur_PK-fasih-medium"."""
        return f"{self.engine}:{self.voice_id}"


def _load_catalogs() -> tuple[VoiceOption, ...]:
    """Read the bundled Piper and Kokoro catalogs, keeping the app's dubbing languages."""
    languages = {code for _, code in DubbingDefaults.LANGUAGES}
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


def xtts_voice(language: str) -> VoiceOption:
    """The cloning pseudo-voice for one XTTS language, bridged through another script if needed."""
    if language in XTTS_LANGUAGES:
        return VoiceOption(
            engine=ENGINE_XTTS, voice_id="clone", language=language,
            label="Clone the original speaker", model_path=XTTS_LANGUAGES[language],
        )
    bridge = XTTS_SCRIPT_BRIDGE[language]
    return VoiceOption(
        engine=ENGINE_XTTS, voice_id="clone", language=language,
        label=f"Clone the original speaker (read in {_SCRIPT_NAMES[bridge]} script)",
        model_path=XTTS_LANGUAGES[bridge], bridge=bridge,
    )


def engine_supports(engine: str, language: str, bridge: bool = True) -> bool:
    """True when `engine` can speak `language`; `bridge` lets XTTS read it in another script."""
    if engine == ENGINE_XTTS:
        return language in XTTS_LANGUAGES or (bridge and language in XTTS_SCRIPT_BRIDGE)
    return any(v.engine == engine and v.language == language for v in VOICES)


def voices_for(engine: str, language: str, bridge: bool = True) -> list[VoiceOption]:
    """Voices `engine` offers for `language`, best first."""
    if engine == ENGINE_XTTS:
        return [xtts_voice(language)] if engine_supports(engine, language, bridge) else []
    voices = [v for v in VOICES if v.engine == engine and v.language == language]
    preferred = _PREFERRED_PIPER.get(language) if engine == ENGINE_PIPER else None
    return sorted(voices, key=lambda v: v.voice_id != preferred)


def voice_by_key(key: str) -> Optional[VoiceOption]:
    """Look a Kokoro or Piper voice up by its key; None when the catalog has no such voice."""
    return next((v for v in VOICES if v.key == key), None)


def resolve_voice(
    language: str,
    mode: str,
    voice_key: str = DubbingDefaults.VOICE_AUTO,
    can_clone: bool = True,
    bridge: bool = DubbingDefaults.SCRIPT_BRIDGE,
) -> tuple[VoiceOption, Optional[str]]:
    """Choose the voice to dub `language` with, and a note when it isn't the requested one.

    The requested mode wins whenever it can speak the language (and, for XTTS, a reference
    recording exists to clone). Otherwise the next engine in XTTS, Kokoro, Piper order is used.
    With `bridge`, XTTS speaks Urdu by reading it in Hindi script, which the note says.
    Raises ValueError when no engine speaks the language or a named voice is for another one.
    """
    def usable(engine: str) -> bool:
        return engine_supports(engine, language, bridge) and (engine != ENGINE_XTTS or can_clone)

    engine = mode if usable(mode) else next((e for e in ENGINES if usable(e)), None)
    if engine is None:
        raise ValueError(f"No dubbing voice speaks '{language}'.")
    warning = None
    if engine != mode:
        reason = "has no original voice to clone" if mode == ENGINE_XTTS and engine_supports(mode, language, bridge) \
            else f"can't speak '{language}'"
        warning = f"{ENGINE_LABELS[mode]} {reason}, so {ENGINE_LABELS[engine]} was used instead."
    elif engine == ENGINE_XTTS and language in XTTS_SCRIPT_BRIDGE:
        script = _SCRIPT_NAMES[XTTS_SCRIPT_BRIDGE[language]]
        warning = (
            f"{ENGINE_LABELS[engine]} can't speak '{language}' directly, so it read the lines in "
            f"{script} script with the cloned voices; a few words may sound {script}-accented."
        )
    if engine == mode and voice_key != DubbingDefaults.VOICE_AUTO and engine != ENGINE_XTTS:
        voice = voice_by_key(voice_key)
        if voice is None or voice.engine != engine:
            raise ValueError(f"Unknown {ENGINE_LABELS[engine]} voice: {voice_key}.")
        if voice.language != language:
            raise ValueError(f"The voice {voice.label} speaks '{voice.language}', not '{language}'.")
        return voice, warning
    return voices_for(engine, language)[0], warning
