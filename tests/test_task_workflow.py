# test_task_workflow.py - unit tests for workflow validation and step chaining

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ccgen.core.tasks import TASK_CONFIG
from ccgen.core.tasks.workflow import WorkflowTask
from tests.test_task_dub import FakeEngine, _write_media
from tests.test_task_translate import _FaithfulMeaning, _fake_translate

_SEGMENTS = [{
    "id": 0, "start": 0.0, "end": 2.0, "text": " Hello world.", "language": "en",
    "words": [{"word": " Hello", "start": 0.0, "end": 0.8}, {"word": " world.", "start": 0.8, "end": 2.0}],
}]


def _workflow(input_path, *steps, **extra):
    """Validate a workflow body into its config."""
    return TASK_CONFIG.validate_python({"task": "workflow", "input_path": str(input_path), "steps": list(steps), **extra})


class TestValidation:
    def test_needs_a_step(self, tmp_path):
        with pytest.raises(ValueError, match="at least one step"):
            _workflow(tmp_path / "a.mp4")

    def test_generate_needs_media(self, tmp_path):
        with pytest.raises(ValueError, match="Step 1 \\(generate\\) needs a video or audio file"):
            _workflow(tmp_path / "a.srt", {"kind": "generate"})

    def test_text_steps_need_text_input(self, tmp_path):
        with pytest.raises(ValueError, match="Step 1 \\(translate\\) needs text"):
            _workflow(tmp_path / "a.mp4", {"kind": "translate", "target_lang": "ur"})

    def test_inputs_must_come_earlier(self, tmp_path):
        with pytest.raises(ValueError, match="a step that comes before it"):
            _workflow(tmp_path / "a.mp4", {"kind": "generate"}, {"kind": "translate", "input": "step:1"})

    def test_dub_produces_no_text(self, tmp_path):
        with pytest.raises(ValueError, match="a dub produces no text"):
            _workflow(
                tmp_path / "a.mp4", {"kind": "generate"}, {"kind": "dub", "input": "step:0", "mode": "piper"},
                {"kind": "translate", "input": "step:1"},
            )

    def test_steps_writing_the_same_files_are_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Steps 2 and 3 would write the same files"):
            _workflow(
                tmp_path / "a.mp4", {"kind": "generate"},
                {"kind": "translate", "input": "step:0", "target_lang": "es"},
                {"kind": "translate", "input": "step:0", "target_lang": "es"},
            )

    def test_a_voice_must_suit_the_step(self, tmp_path):
        with pytest.raises(ValueError, match="isn't one of the chosen voices"):
            _workflow(tmp_path / "a.srt", {"kind": "dub", "mode": "kokoro", "voice": "piper:ur_PK-fasih-medium",
                                           "output": "wav"})

    def test_step_options_are_validated(self, tmp_path):
        with pytest.raises(ValueError, match="different from the source"):
            _workflow(tmp_path / "a.srt", {"kind": "translate", "source_lang": "en", "target_lang": "en"})

    def test_valid_chain(self, tmp_path):
        cfg = _workflow(
            tmp_path / "a.mp4", {"kind": "generate"},
            {"kind": "translate", "input": "step:0", "target_lang": "es"},
            {"kind": "dub", "input": "step:1"},
        )
        assert [s.kind for s in cfg.steps] == ["generate", "translate", "dub"]


class TestRun:
    @pytest.fixture
    def engines(self):
        """Patch every engine factory the workflow uses."""
        with (
            patch("ccgen.core.tasks.workflow.create_caption_engine") as captions,
            patch("ccgen.core.tasks.translate.create_translation_engine") as translation,
            patch("ccgen.core.tasks.translate.MeaningCheck", _FaithfulMeaning),
            patch("ccgen.core.tasks.workflow.load_audio", return_value=np.zeros(16000, dtype=np.float32)),
            patch("ccgen.core.tasks.dub.create_engine") as speech,
        ):
            captions.return_value.transcribe.return_value = _SEGMENTS
            translator = MagicMock()
            translator.translate_segments.side_effect = _fake_translate
            translation.return_value = translator
            speech.return_value = FakeEngine()
            yield {"captions": captions, "translation": translation, "speech": speech}

    def test_translation_uses_the_detected_language(self, tmp_path, engines):
        media = tmp_path / "movie.mp4"
        media.write_bytes(b"")
        cfg = _workflow(media, {"kind": "generate"}, {"kind": "translate", "input": "step:0", "target_lang": "es"})
        task = WorkflowTask(cfg)
        task.prepare()
        result = task.run()
        assert result.success, result.error
        call = engines["translation"].call_args
        assert (call.args, call.kwargs["profile"], call.kwargs["for_speech"]) == (("auto",), "", False)
        assert (call.kwargs["source_lang"], call.kwargs["target_lang"]) == ("en", "es")
        assert result.output_files == [str(tmp_path / "movie.srt"), str(tmp_path / "movie_es.srt")]
        assert result.detected_language == "en"
        assert result.output_languages == {str(tmp_path / "movie.srt"): "en", str(tmp_path / "movie_es.srt"): "es"}

    def test_steps_can_skip_writing(self, tmp_path, engines):
        media = tmp_path / "movie.mp4"
        media.write_bytes(b"")
        cfg = _workflow(
            media, {"kind": "generate", "write_output": False},
            {"kind": "translate", "input": "step:0", "target_lang": "es"},
        )
        result = WorkflowTask(cfg).run()
        assert result.output_files == [str(tmp_path / "movie_es.srt")]

    def test_generate_translate_dub(self, tmp_path, engines):
        _write_media(tmp_path / "movie.mp4")
        cfg = _workflow(
            tmp_path / "movie.mp4", {"kind": "generate", "write_output": False},
            {"kind": "translate", "input": "step:0", "target_lang": "es", "write_output": False},
            {"kind": "dub", "input": "step:1", "mode": "kokoro"},
        )
        task = WorkflowTask(cfg)
        result = task.run()
        assert result.success, result.error
        assert result.output_files == [str(tmp_path / "movie_dub_es.mkv")]
        assert task.stages == ["load", "transcribe", "translate", "load", "speakers", "speak", "write"]
        assert result.output_languages == {str(tmp_path / "movie_dub_es.mkv"): "es"}
        # The translation feeds the dub, so it is chosen to take about as long to say.
        assert engines["translation"].call_args.kwargs["for_speech"] is True

    def test_subtitle_source_feeds_text_steps(self, tmp_path, engines):
        sub = tmp_path / "talk_en.srt"
        sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nnamaste\n", encoding="utf-8")
        cfg = _workflow(
            sub, {"kind": "transliterate", "source_scheme": "roman", "target_scheme": "hi"},
            {"kind": "translate", "target_lang": "es"},
        )
        result = WorkflowTask(cfg).run()
        assert result.success, result.error
        assert result.output_files == [str(tmp_path / "talk_tr_roman_hi.srt"), str(tmp_path / "talk_es.srt")]

    def test_unknown_language_fails_clearly(self, tmp_path, engines):
        sub = tmp_path / "talk.srt"
        sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
        result = WorkflowTask(_workflow(sub, {"kind": "translate", "target_lang": "es"})).run()
        assert not result.success and "Choose its source language" in result.error
