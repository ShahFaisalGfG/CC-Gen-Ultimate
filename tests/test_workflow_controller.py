# test_workflow_controller.py - step list editing and job bodies for the Workflow tab

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.controllers.workflow_ctrl import WorkflowController
from tests.test_task_controller import _FakeApi


@pytest.fixture
def ctrl():
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    controller = WorkflowController(base_url="http://127.0.0.1:1")
    controller._api = _FakeApi()  # type: ignore[assignment]
    return controller


def _steps(ctrl):
    return ctrl.steps.steps


class TestSteps:
    def test_starts_with_generate_then_translate(self, ctrl):
        assert [s["kind"] for s in _steps(ctrl)] == ["generate", "translate"]
        assert _steps(ctrl)[1]["input"] == "step:0"

    def test_new_step_reads_the_nearest_text_step(self, ctrl):
        ctrl.addStep("dub")
        assert _steps(ctrl)[2]["input"] == "step:1"
        ctrl.addStep("transliterate")
        assert _steps(ctrl)[3]["input"] == "step:1"  # a dub produces no text

    def test_removing_a_later_step_keeps_earlier_references(self, ctrl):
        ctrl.addStep("translate")
        ctrl.setStepOption(2, "input", "step:0")
        ctrl.addStep("dub")
        ctrl.setStepOption(3, "input", "step:1")
        ctrl.addStep("transliterate")
        ctrl.removeStep(4)
        assert [s.get("input") for s in _steps(ctrl)] == [None, "step:0", "step:0", "step:1"]

    def test_removing_a_middle_step_shifts_later_references(self, ctrl):
        ctrl.addStep("translate")
        ctrl.setStepOption(2, "input", "step:0")
        ctrl.addStep("dub")
        ctrl.setStepOption(3, "input", "step:2")
        ctrl.removeStep(1)
        assert [s.get("input") for s in _steps(ctrl)] == [None, "step:0", "step:1"]

    def test_dub_step_voice_resets_with_its_mode(self, ctrl):
        ctrl.addStep("dub")
        ctrl.setStepOption(2, "mode", "piper")
        ctrl.setStepOption(2, "voice", "piper:ur_PK-fasih-medium")
        ctrl.setStepOption(2, "mode", "kokoro")
        assert _steps(ctrl)[2]["voice"] == "auto"

    def test_removing_an_input_falls_back_to_an_earlier_step(self, ctrl):
        ctrl.addStep("dub")
        ctrl.removeStep(1)
        assert _steps(ctrl)[1]["input"] == "step:0"

    def test_moving_keeps_references_that_still_come_first(self, ctrl):
        ctrl.addStep("transliterate")
        ctrl.setStepOption(2, "input", "step:0")
        ctrl.moveStep(2, 1)
        assert [s["kind"] for s in _steps(ctrl)] == ["generate", "transliterate", "translate"]
        assert _steps(ctrl)[1]["input"] == "step:0"
        assert _steps(ctrl)[2]["input"] == "step:0"

    def test_moving_above_its_input_resets_the_reference(self, ctrl):
        ctrl.moveStep(1, 0)
        assert _steps(ctrl)[0]["input"] == "source"

    def test_inputs_list_earlier_text_steps(self, ctrl):
        index = ctrl.steps.index(1)
        inputs = ctrl.steps.data(index, ctrl.steps.InputsRole)
        assert [i["code"] for i in inputs] == ["source", "step:0"]
        assert inputs[1]["label"] == "Step 1: Generate subtitles"

    def test_titles_follow_options(self, ctrl):
        ctrl.setStepOption(1, "target_lang", "ur")
        assert ctrl.steps.data(ctrl.steps.index(1), ctrl.steps.TitleRole) == "Translate to Urdu"

    def test_saved_preferences_refresh_untouched_starter_steps(self, ctrl):
        ctrl._api.settings = {"translation": {"target_lang": "fr"}}
        ctrl.reloadDefaults()
        assert _steps(ctrl)[1]["target_lang"] == "fr"
        ctrl.setStepOption(1, "target_lang", "es")
        ctrl.reloadDefaults()
        assert _steps(ctrl)[1]["target_lang"] == "es"


class TestJobBody:
    def test_body_validates_as_a_workflow(self, ctrl, tmp_path):
        from ccgen.api.schemas.job import config_errors

        ctrl.addStep("dub")
        media = tmp_path / "m.mp4"
        body = ctrl.job_body({"path": str(media), "language": "", "companion": ""})
        assert body["steps"][0]["language"] is None
        assert config_errors(body) == []

    def test_subtitle_source_language_is_passed_to_steps_reading_it(self, ctrl, tmp_path):
        ctrl.removeStep(0)
        body = ctrl.job_body({"path": str(tmp_path / "m.srt"), "language": "en", "companion": ""})
        assert body["steps"][0]["input"] == "source"
        assert body["text_language"] == "en"

    def test_chosen_language_wins_over_the_file_name(self, ctrl, tmp_path):
        ctrl.removeStep(0)
        item = {"path": str(tmp_path / "m_en.srt"), "language": "en", "chosen_language": "fr", "companion": ""}
        assert ctrl.job_body(item)["text_language"] == "fr"

    def test_step_detecting_the_language_of_an_unnamed_subtitle_blocks_start(self, ctrl, tmp_path):
        (tmp_path / "talk.srt").write_text("")
        ctrl.removeStep(0)
        ctrl.addFiles([str(tmp_path / "talk.srt")])
        ctrl._validate()
        assert ctrl.needsSubtitleLanguage
        assert ctrl.blocker.startswith("talk.srt has no known language, which step 1")
        ctrl.setStepOption(0, "source_lang", "en")
        assert not ctrl.needsSubtitleLanguage
        ctrl._validate()
        assert "no known language" not in ctrl.blocker
        ctrl.setStepOption(0, "source_lang", "auto")
        ctrl.fileModel.setChosenLanguage(0, "fr")
        ctrl._validate()
        assert "no known language" not in ctrl.blocker
