# prefs_ctrl.py - preferences controller (HTTP client of the embedded API)

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from ccgen.config.defaults import (
    ComputeDefaults,
    DubbingDefaults,
    LanguageOptions,
    ModelDefaults,
    OutputDefaults,
    TransliterationDefaults,
    get_default_settings,
)
from ccgen.config.translation_models import ENGINES as TRANSLATION_ENGINES
from ccgen.controllers.api_client import ApiClient


def _items(pairs: list) -> list[dict[str, str]]:
    """Convert (label, code) tuples into the {label, code} dicts QML combo boxes use."""
    return [{"label": label, "code": code or ""} for label, code in pairs]


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
        """Whisper models with size and a short speed/accuracy note."""
        return [
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
