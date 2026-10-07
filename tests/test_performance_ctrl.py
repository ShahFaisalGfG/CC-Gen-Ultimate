# test_performance_ctrl.py - the recommended profile is applied on first launch and follows
# hardware changes only while the user hasn't chosen a profile by hand

from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.controllers.performance_ctrl import PerformanceController
from ccgen.engines.hardware import HardwareProfile

_STRONG = HardwareProfile(gpu="NVIDIA RTX 4090", vram_gb=24.0, ram_gb=64.0, physical_cores=16)
_WEAK = HardwareProfile(gpu="", vram_gb=0.0, ram_gb=8.0, physical_cores=4)


class _FakeApi:
    """Answers GET /settings with `settings` and records PATCH bodies."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.patches: list[dict[str, Any]] = []

    def get(self, path, handler=None):
        handler(self.settings, "")

    def patch(self, path, body, handler=None):
        self.patches.append(body["values"])
        if handler is not None:
            handler({}, "")


@pytest.fixture
def controller():
    if QCoreApplication.instance() is None:
        QCoreApplication([])

    def build(performance: dict[str, Any]):
        ctrl = PerformanceController(base_url="http://127.0.0.1:1")
        ctrl._api = _FakeApi({"performance": performance})  # type: ignore[assignment]
        notices: list[str] = []
        ctrl.notice.connect(notices.append)
        return ctrl, notices

    return build


def _performance(profile="", recommended="", hardware_id="") -> dict[str, str]:
    return {"profile": profile, "recommended": recommended, "hardware": "", "hardware_id": hardware_id}


class TestApplyProfile:
    def test_first_launch_applies_the_recommendation_once_and_says_so(self, controller):
        ctrl, notices = controller(_performance())
        ctrl._on_detected(_STRONG)
        assert ctrl._api.patches[0]["performance.profile"] == "quality"
        assert notices == ["CC-Gen chose the Maximum quality profile for this PC. Change it in Preferences > Performance."]

    def test_unchanged_hardware_saves_nothing_and_stays_quiet(self, controller):
        ctrl, notices = controller(_performance("light", "light", _WEAK.fingerprint))
        ctrl._api.settings["performance"]["hardware"] = _WEAK.summary
        ctrl._on_detected(_WEAK)
        assert ctrl._api.patches == [] and notices == []

    def test_new_hardware_switches_a_profile_the_user_never_chose(self, controller):
        ctrl, notices = controller(_performance("light", "light", _WEAK.fingerprint))
        ctrl._on_detected(_STRONG)
        assert ctrl._api.patches[0]["performance.profile"] == "quality"
        assert "switched to the Maximum quality profile" in notices[0]

    def test_new_hardware_only_suggests_when_the_user_chose_a_profile(self, controller):
        ctrl, notices = controller(_performance("balanced", "light", _WEAK.fingerprint))
        ctrl._on_detected(_STRONG)
        assert "performance.profile" not in ctrl._api.patches[0]
        assert ctrl._api.patches[0]["performance.recommended"] == "quality"
        assert "now suits it best" in notices[0]

    def test_new_hardware_keeps_a_custom_profile(self, controller):
        ctrl, notices = controller(_performance("custom", "light", _WEAK.fingerprint))
        ctrl._on_detected(_STRONG)
        assert "performance.profile" not in ctrl._api.patches[0]
        assert ctrl._api.patches[0]["performance.recommended"] == "quality"
        assert "Custom profile now follow the Maximum quality profile" in notices[0]

    def test_profile_options_end_with_custom(self, controller):
        ctrl, _ = controller(_performance())
        assert [p["code"] for p in ctrl.profileOptions][-1] == "custom"

    def test_failed_detection_changes_nothing(self, controller):
        ctrl, notices = controller(_performance())
        ctrl._on_detected(None)
        assert ctrl._api.patches == [] and notices == [] and not ctrl.detecting
