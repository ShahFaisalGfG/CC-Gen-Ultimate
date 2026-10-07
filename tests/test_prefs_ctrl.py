# test_prefs_ctrl.py - the Performance page summary: a profile's Automatic choices, models
# chosen by hand, and the Custom profile's recommendation

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.config.defaults import get_default_settings
from ccgen.controllers.prefs_ctrl import PrefsController

_AUTOMATIC = {"model.name": "auto", "translation.engine": "auto", "transliteration.engine": "auto",
              "dubbing.mode": "auto", "dubbing.quality": "auto"}


@pytest.fixture
def prefs():
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    ctrl = PrefsController(base_url="http://127.0.0.1:1")
    settings = get_default_settings()
    settings["performance"]["recommended"] = "quality"
    ctrl._settings = settings
    return ctrl


def _choices(rows):
    return {row["feature"]: row["choice"] for row in rows}


class TestProfileSummary:
    def test_a_preset_lists_its_automatic_choices(self, prefs):
        rows = _choices(prefs.profileSummary("light", _AUTOMATIC))
        assert rows["Subtitle generation"] == "Whisper small"
        assert rows["Dubbing"] == "OmniVoice voice cloning, fast mode"

    def test_models_chosen_by_hand_are_marked(self, prefs):
        rows = _choices(prefs.profileSummary("light", {**_AUTOMATIC, "model.name": "large-v3-turbo",
                                                       "translation.engine": "nllb"}))
        assert rows["Subtitle generation"] == "Whisper large-v3-turbo (chosen by hand)"
        assert rows["Translation"].endswith("(chosen by hand)") and "NLLB" in rows["Translation"]

    def test_a_quality_chosen_by_hand_shows_on_the_dubbing_row(self, prefs):
        rows = _choices(prefs.profileSummary("light", {**_AUTOMATIC, "dubbing.quality": "full"}))
        assert rows["Dubbing"] == "OmniVoice voice cloning, full quality (chosen by hand)"

    def test_custom_resolves_automatic_with_this_pcs_recommendation(self, prefs):
        rows = _choices(prefs.profileSummary("custom", {}))
        assert rows["Subtitle generation"] == "Whisper large-v3"
        assert rows["Dubbing"] == "OmniVoice voice cloning, full quality"
