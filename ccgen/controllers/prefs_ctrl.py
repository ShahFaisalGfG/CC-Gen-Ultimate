# prefs_ctrl.py - preferences controller (HTTP client of the embedded API)

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from ccgen.config import licences, profiles
from ccgen.config.defaults import (
    AUTO,
    ComputeDefaults,
    DubbingDefaults,
    LanguageOptions,
    ModelDefaults,
    OutputDefaults,
    TransliterationDefaults,
    get_default_settings,
)
from ccgen.config.translation_models import ENGINES as TRANSLATION_ENGINES
from ccgen.config.translation_models import engine_info as translation_engine_info
from ccgen.config.voices import CLONING_ENGINES, ENGINE_LABELS
from ccgen.controllers.api_client import ApiClient


def _items(pairs: list) -> list[dict[str, str]]:
    """Convert (label, code) tuples into the {label, code} dicts QML combo boxes use."""
    return [{"label": label, "code": code or ""} for label, code in pairs]


def _summary_row(feature: str, automatic: str, by_hand: bool, chosen: str) -> dict[str, str]:
    """One Performance page row: the profile's Automatic choice, or what was chosen by hand."""
    return {"feature": feature, "choice": f"{chosen} (chosen by hand)" if by_hand else automatic}


class PrefsController(QObject):
    """Exposes saved preferences and option lists to QML, backed by the embedded API."""

    settingsChanged = Signal()
    saveFinished = Signal(bool, str)  # (success, error message)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self._api = ApiClient(base_url, self)
        self._settings: dict[str, Any] = get_default_settings()
        self.loadSettings()

    # ── Saved settings ───────────────────────────────────────────────────────

    @Property("QVariantMap", notify=settingsChanged)  # type: ignore[arg-type]
    def settings(self) -> dict:
        """The full saved settings dictionary, grouped by section."""
        return self._settings

    @Slot()
    def loadSettings(self) -> None:
        """Re-fetch settings from the embedded API and notify QML."""
        self._api.get("/settings", self._on_settings)

    @Slot("QVariantMap")
    def saveSettings(self, values: dict) -> None:
        """Save several dot-separated keys (e.g. {"model.name": "small"}) in one atomic write."""
        self._api.patch("/settings", {"values": dict(values)}, self._on_saved)

    @Slot()
    def resetDefaults(self) -> None:
        """Reset every preference to its factory default."""
        self._api.post("/settings/reset", None, self._on_saved)

    @Property(str, notify=settingsChanged)  # type: ignore[arg-type]
    def profile(self) -> str:
        """The saved performance profile, Custom included ("" until detected)."""
        return profiles.saved_profile(self._settings)

    # ── Performance profiles and Automatic choices ───────────────────────────

    @Slot(str, "QVariantMap", result=list)
    def profileSummary(self, profile: str, choices: dict) -> list:
        """What each feature runs with on a profile, for the Performance page: the profile's
        Automatic choice, or the model chosen by hand. `choices` maps the model settings being
        edited (model.name, translation.engine, transliteration.engine, dubbing.mode,
        dubbing.quality) to their values; Custom resolves Automatic with this PC's recommendation.
        """
        if profile == profiles.PROFILE_CUSTOM:
            profile = str(self._settings.get("performance", {}).get("recommended") or "")
        automatic = dict(profiles.describe(profile))

        def pick(key: str) -> str:
            return str(choices.get(key) or AUTO)

        whisper, engine, translit = pick("model.name"), pick("translation.engine"), pick("transliteration.engine")
        mode, quality = pick("dubbing.mode"), pick("dubbing.quality")
        translit_labels = {code: label for label, code in TransliterationDefaults.ENGINES}
        dub = profiles.dub_engine(mode, profile, quality)
        dub_label = (f"{ENGINE_LABELS[dub.mode]} voice cloning" if dub.mode in CLONING_ENGINES
                     else {code: label for label, code, _ in DubbingDefaults.MODES}[dub.mode])
        if dub.mode == DubbingDefaults.MODE_OMNIVOICE:
            dub_label += ", fast mode" if dub.fast else ", full quality"
        return [
            _summary_row("Subtitle generation", automatic["Subtitle generation"], whisper != AUTO, f"Whisper {whisper}"),
            _summary_row("Translation", automatic["Translation"], engine != AUTO,
                         translation_engine_info(engine).label if engine != AUTO else ""),
            _summary_row("Transliteration", automatic["Transliteration"], translit != AUTO,
                         translit_labels.get(translit, "")),
            _summary_row("Dubbing", automatic["Dubbing"], (mode, quality) != (AUTO, AUTO), dub_label),
        ]

    @Slot(str, "QVariantMap", "QVariantMap", result=str)
    def automaticChoice(self, kind: str, options: dict, settings: dict) -> str:
        """Which model an Automatic choice runs with these options, e.g. "Whisper small" ("" when
        the choice isn't Automatic). `settings` is passed so QML bindings update when they change.
        """
        profile = profiles.effective_profile(settings)
        if kind == "generate" and options.get("model_name") == AUTO:
            return f"Whisper {profiles.whisper_model(AUTO, profile)}"
        if kind == "translate" and options.get("engine") == AUTO:
            engines = profiles.translation_engines(
                AUTO, profile, str(options.get("source_lang") or "auto"), str(options.get("target_lang") or ""),
            )
            return ", ".join(sorted(translation_engine_info(e).label for e in engines))
        if kind == "transliterate" and options.get("engine") == AUTO:
            engine = profiles.transliteration_engine(
                AUTO, profile, str(options.get("source_scheme") or ""), str(options.get("target_scheme") or ""),
            )
            return dict((code, label) for label, code in TransliterationDefaults.ENGINES)[engine]
        if kind == "dub" and options.get("mode") == AUTO:
            choice = profiles.dub_engine(AUTO, profile, str(options.get("quality") or AUTO))
            return f"{ENGINE_LABELS[choice.mode]} voice cloning, {'fast mode' if choice.fast else 'full quality'}"
        return ""

    @Slot("QVariantMap", "QVariantMap", result=str)
    def resolvedTranslitEngine(self, options: dict, settings: dict) -> str:
        """The transliteration engine an engine setting runs with ("auto" resolves with the profile)."""
        return profiles.transliteration_engine(
            str(options.get("engine") or AUTO), profiles.effective_profile(settings),
            str(options.get("source_scheme") or ""), str(options.get("target_scheme") or ""),
        )

    @Slot(str, "QVariantMap", result=str)
    def resolvedDubMode(self, mode: str, settings: dict) -> str:
        """The dubbing engine a mode setting runs with ("auto" resolves with the profile)."""
        return profiles.dub_engine(mode or AUTO, profiles.effective_profile(settings)).mode

    @Slot(str, "QVariantMap", "QVariantMap", result=str)
    def pendingLicence(self, kind: str, options: dict, settings: dict) -> str:
        """The model whose licence must still be accepted for these translate or dub options, or ""."""
        if kind == "translate":
            source, target = str(options.get("source_lang") or "auto"), str(options.get("target_lang") or "")
            models = profiles.translation_engines(str(options.get("engine") or AUTO),
                                                  profiles.effective_profile(settings), source, target)
        elif kind == "dub":
            models = {profiles.dub_engine(str(options.get("mode") or AUTO), profiles.effective_profile(settings)).mode}
        else:
            return ""
        return licences.pending(settings, sorted(models))

    @Slot(str, result="QVariantMap")
    def modelTerms(self, key: str) -> dict:
        """A model's licence notice (title, body, note, url, site, setting) for the licence dialog."""
        return licences.terms_dict(key)

    def _on_settings(self, data: Any, error: str) -> None:
        """Apply a fetched settings snapshot."""
        if not error and isinstance(data, dict):
            self._settings = data
            self.settingsChanged.emit()

    def _on_saved(self, data: Any, error: str) -> None:
        """Apply the server's updated snapshot and report the outcome."""
        self._on_settings(data, error)
        self.saveFinished.emit(not error, error)

    # ── Option lists ─────────────────────────────────────────────────────────

    @Property(list, constant=True)
    def themeOptions(self) -> list:
        """Theme choices."""
        return _items([("System (follow Windows)", "system"), ("Light", "light"), ("Dark", "dark")])

    @Property(list, constant=True)
    def modelOptions(self) -> list:
        """Whisper models with size and a short speed/accuracy note, after the Automatic choice."""
        automatic = {"label": "Automatic (recommended)", "code": AUTO, "sizeMb": 0}
        return [automatic] + [
            {
                "label": f"{name} - {ModelDefaults.MODEL_NOTES[name]}",
                "code": name,
                "sizeMb": ModelDefaults.MODEL_SIZES_MB[name],
            }
            for name in ModelDefaults.SUPPORTED_MODELS
        ]

    @Property(list, constant=True)
    def deviceOptions(self) -> list:
        """Compute device choices for transcription."""
        return _items(ComputeDefaults.DEVICES)

    @Property(list, constant=True)
    def languageOptions(self) -> list:
        """Transcription languages; code "" means auto-detect."""
        return _items(LanguageOptions.TRANSCRIPTION)

    @Property(list, constant=True)
    def targetOptions(self) -> list:
        """Translation target languages."""
        return _items(LanguageOptions.TRANSLATION_TARGETS)

    @Property(list, constant=True)
    def translationEngineOptions(self) -> list:
        """Translation models with the trade-offs of each, the recommended one first."""
        return [{"label": e.label, "code": e.key, "hint": e.hint} for e in TRANSLATION_ENGINES]

    @Property(list, constant=True)
    def sourceOptions(self) -> list:
        """Languages subtitles can be translated from; "auto" uses each file's known language."""
        return _items([("Detect from each file", "auto")] + LanguageOptions.TRANSLATION_TARGETS)

    @Property(list, constant=True)
    def translitSchemeOptions(self) -> list:
        """Transliteration scripts."""
        return _items(TransliterationDefaults.SCHEMES)

    @Property(list, constant=True)
    def translitEngineOptions(self) -> list:
        """Transliteration engines."""
        return _items(TransliterationDefaults.ENGINES)

    @Property(list, constant=True)
    def dubModeOptions(self) -> list:
        """Dubbing modes with the trade-offs of each, voice cloning first."""
        return [{"label": label, "code": code, "hint": hint} for label, code, hint in DubbingDefaults.MODES]

    @Property(list, constant=True)
    def dubQualityOptions(self) -> list:
        """How carefully voice cloning refines its speech, with the trade-off of each."""
        return [{"label": label, "code": code, "hint": hint} for label, code, hint in DubbingDefaults.QUALITIES]

    @Property(list, constant=True)
    def dubLanguageOptions(self) -> list:
        """Languages a dub can speak; "auto" uses the subtitle's language."""
        return _items([("Same as the subtitles", DubbingDefaults.LANGUAGE_AUTO)] + DubbingDefaults.LANGUAGES)

    @Property(list, constant=True)
    def speakerOptions(self) -> list:
        """How voice cloning treats several speakers."""
        return _items(DubbingDefaults.SPEAKERS)

    @Property(list, constant=True)
    def dubOutputOptions(self) -> list:
        """Where the dub goes: a new track in a copy of the media, or a separate WAV file."""
        return _items(DubbingDefaults.OUTPUTS)

    @Property(list, constant=True)
    def dubDeviceOptions(self) -> list:
        """Devices speech synthesis may use."""
        return _items(DubbingDefaults.DEVICES)

    @Property(list, constant=True)
    def speedupRange(self) -> list:
        """Allowed [min, max] speech speed-up for fitting a line into its time."""
        return list(DubbingDefaults.MAX_SPEEDUP_RANGE)

    @Property(list, constant=True)
    def logLevelOptions(self) -> list:
        """Log detail levels."""
        return _items([("Warnings and errors", "critical"), ("Everything (for troubleshooting)", "all")])

    @Property(list, constant=True)
    def lineLengthRange(self) -> list:
        """Allowed [min, max] characters per subtitle line."""
        return list(OutputDefaults.MAX_LINE_LENGTH_RANGE)

    @Property(list, constant=True)
    def maxLinesRange(self) -> list:
        """Allowed [min, max] lines per subtitle cue."""
        return list(OutputDefaults.MAX_LINES_RANGE)
