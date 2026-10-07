# performance_ctrl.py - detects this PC's hardware and keeps the performance profile suited to it
#
# On every start the hardware is measured off the UI thread. The first time (no profile saved
# yet), the recommended profile is applied and a one-time note says so. When the hardware later
# changes, the new recommendation replaces the profile only if the user never chose one by hand
# (the saved profile is still the previous recommendation); otherwise the note only suggests it.
# A Custom profile is kept; its Automatic choices follow the new recommendation.

import logging
from typing import Any

from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, Signal, Slot

from ccgen.config.profiles import PROFILE_CHOICES, PROFILE_CUSTOM, profile_info, saved_profile
from ccgen.controllers.api_client import ApiClient

_log = logging.getLogger(__name__)


class _DetectSignals(QObject):
    finished = Signal(object)  # HardwareProfile, or None when detection failed


class _DetectWorker(QRunnable):
    """Runs hardware detection (which imports torch) on the thread pool."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = _DetectSignals()

    @Slot()
    def run(self) -> None:
        try:
            from ccgen.engines.hardware import detect

            self.signals.finished.emit(detect())
        except Exception as e:  # detection is advisory; the app works without it
            _log.error("Hardware detection failed: %r", e, exc_info=True)
            self.signals.finished.emit(None)


class PerformanceController(QObject):
    """Exposes the detected hardware and applies the recommended performance profile."""

    detectingChanged = Signal()
    # A one-off message for the main window (shown as a toast).
    notice = Signal(str)
    # The profile or hardware was saved; Preferences and the tabs reload their settings.
    settingsSaved = Signal()

    def __init__(self, base_url: str, parent: Any = None) -> None:
        super().__init__(parent)
        self._api = ApiClient(base_url, self)
        self._detecting = False
        self._worker: _DetectWorker | None = None

    @Property(bool, notify=detectingChanged)  # type: ignore[arg-type]
    def detecting(self) -> bool:
        """True while the hardware is being measured."""
        return self._detecting

    @Property(list, constant=True)
    def profileOptions(self) -> list:
        """The performance profiles, best quality first, then Custom."""
        return [{"label": p.label, "code": p.key, "hint": p.hint} for p in PROFILE_CHOICES]

    @Slot()
    def detect(self) -> None:
        """Measure the hardware again (Preferences > Performance > Detect again, and on start)."""
        if self._detecting:
            return
        self._detecting = True
        self.detectingChanged.emit()
        self._worker = _DetectWorker()
        self._worker.signals.finished.connect(self._on_detected)
        QThreadPool.globalInstance().start(self._worker)

    def _on_detected(self, hardware: Any) -> None:
        self._detecting = False
        self._worker = None
        self.detectingChanged.emit()
        if hardware is None:
            return
        # The latest saved settings decide whether the profile may change.
        self._api.get("/settings", lambda data, error: self._apply(hardware, data, error))

    def _apply(self, hardware: Any, settings: Any, error: str) -> None:
        if error or not isinstance(settings, dict):
            return
        performance = settings.get("performance", {})
        current = saved_profile(settings)
        recommended = hardware.recommended
        values: dict[str, Any] = {
            "performance.hardware": hardware.summary,
            "performance.hardware_id": hardware.fingerprint,
            "performance.recommended": recommended,
        }
        changed = performance.get("hardware_id") != hardware.fingerprint
        label = profile_info(recommended).label
        if not current:
            values["performance.profile"] = recommended
            self.notice.emit(f"CC-Gen chose the {label} profile for this PC. Change it in Preferences > Performance.")
        elif changed and current == PROFILE_CUSTOM:
            self.notice.emit(f"This PC's hardware changed; Automatic choices in your Custom profile now "
                             f"follow the {label} profile.")
        elif changed and current != recommended:
            if current == performance.get("recommended"):
                values["performance.profile"] = recommended
                self.notice.emit(f"This PC's hardware changed, so CC-Gen switched to the {label} profile.")
            else:
                self.notice.emit(f"This PC's hardware changed; the {label} profile now suits it best "
                                 "(Preferences > Performance).")
        if values != {key: performance.get(key.split(".")[1]) for key in values}:
            self._api.patch("/settings", {"values": values}, self._on_saved)

    def _on_saved(self, data: Any, error: str) -> None:
        if error:
            _log.warning("Saving the performance profile failed: %s", error)
            return
        self.settingsSaved.emit()
