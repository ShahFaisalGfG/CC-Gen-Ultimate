# test_task_controller.py - queue runner and tab tests for ccgen.controllers.task_ctrl / task_tabs
#
# The embedded API is replaced by a fake client that records requests and lets each test
# play back job events, so the queue logic runs without a server, sockets, or models.

from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.controllers.task_tabs import (
    DubController,
    GenerateController,
    TranslateController,
    TransliterateController,
)
from ccgen.models.file_model import MediaFileModel


class _FakeSocket:
    """Stands in for QWebSocket: only the bits the controller touches."""

    class _Signal:
        def connect(self, *_):
            pass

        def disconnect(self, *_):
            pass

    errorOccurred = _Signal()

    def close(self):
        pass

    def deleteLater(self):
        pass


class _FakeApi:
    """Records calls, hands job ids out in order, and answers validation with `errors`."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, Any]] = []
        self.streams: dict[str, Any] = {}
        self.errors: list[str] = []
        self.settings: Any = None
        self._next_job = 0

    def get(self, path, handler=None):
        if path == "/settings" and handler is not None and self.settings is not None:
            handler(self.settings, "")

    def post(self, path, body=None, handler=None):
        self.posts.append((path, body))
        if path == "/jobs" and handler is not None:
            self._next_job += 1
            handler({"job_id": f"job{self._next_job}"}, "")
        elif path == "/jobs/validate" and handler is not None:
            handler({"errors": self.errors}, "")

    def open_stream(self, path, on_message):
        self.streams[path] = on_message
        return _FakeSocket()

    def send(self, job_id: str, event: dict) -> None:
        self.streams[f"/jobs/{job_id}/stream"](event)

    def jobs(self) -> list[dict]:
        return [body for path, body in self.posts if path == "/jobs"]


def _make(cls):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    ctrl = cls(base_url="http://127.0.0.1:1")
    ctrl._api = _FakeApi()  # type: ignore[assignment]
    return ctrl


@pytest.fixture
def controller():
    return _make(GenerateController)


@pytest.fixture
def media(tmp_path):
    paths = []
    for name in ("a.mp4", "b.mp3", "c.wav"):
        path = tmp_path / name
        path.write_bytes(b"data")
        paths.append(str(path))
    return paths


def _status(ctrl, row):
    return ctrl.fileModel.data(ctrl.fileModel.index(row), MediaFileModel.StatusRole)


def _finish(ctrl, job, success=True, outputs=None, **extra):
    """Play back a job's finished event."""
    ctrl._api.send(job, {"event": "finished", "success": success, "error": "" if success else "boom",
                         "output_files": outputs or [], **extra})


class TestQueue:
    def test_runs_files_in_order(self, controller, media):
        controller.addFiles(media)
        controller.startQueue()
        assert [b["input_path"] for b in controller._api.jobs()] == [media[0]]
        _finish(controller, "job1")
        _finish(controller, "job2")
        _finish(controller, "job3")
        assert [b["input_path"] for b in controller._api.jobs()] == media
        assert not controller.busy
        assert controller.summary == "3 of 3 files done."

    def test_failure_continues_with_next_file(self, controller, media):
        controller.addFiles(media[:2])
        controller.startQueue()
        _finish(controller, "job1", success=False)
        _finish(controller, "job2")
        assert [_status(controller, r) for r in range(2)] == ["error", "done"]
        assert controller.summary == "1 of 2 files done, 1 failed."

    def test_cancel_then_resume_skips_finished(self, controller, media):
        controller.addFiles(media)
        controller.startQueue()
        _finish(controller, "job1")
        controller.cancelQueue()
        assert ("/jobs/job2/cancel", None) in controller._api.posts
        _finish(controller, "job2", success=False, cancelled=True)
        assert [_status(controller, r) for r in range(3)] == ["done", "cancelled", "pending"]
        controller.startQueue()
        assert controller._api.jobs()[-1]["input_path"] == media[1]

    def test_rerun_when_everything_is_done(self, controller, media):
        controller.addFiles(media[:1])
        controller.startQueue()
        _finish(controller, "job1")
        controller.startQueue()
        assert len(controller._api.jobs()) == 2

    def test_removed_file_is_skipped(self, controller, media):
        controller.addFiles(media)
        controller.startQueue()
        controller.fileModel.removeAt(1)
        _finish(controller, "job1")
        assert controller._api.jobs()[-1]["input_path"] == media[2]

    def test_progress_never_moves_backwards_between_steps(self, controller, media):
        controller.addFiles(media[:1])
        controller.startQueue()
        controller._api.send("job1", {"event": "progress", "done": 9, "total": 10, "step": 0, "steps": 2})
        first = controller.overallProgress
        controller._api.send("job1", {"event": "progress", "done": 1, "total": 10, "step": 1, "steps": 2})
        assert controller.overallProgress > first

    def test_status_message_keeps_the_step_progress(self, controller, media):
        controller.addFiles(media[:1])
        controller.startQueue()
        controller._api.send("job1", {"event": "progress", "done": 10, "total": 10, "step": 1, "steps": 4})
        controller._api.send("job1", {"event": "status", "message": "Preparing...", "step": 1, "steps": 4})
        assert controller.overallProgress == 0.5
        assert controller.stageProgress == -1.0
        row = controller.fileModel.data(controller.fileModel.index(0), MediaFileModel.ProgressRole)
        assert row == controller.fileProgress
        controller._api.send("job1", {"event": "status", "message": "Speaking...", "step": 2, "steps": 4})
        assert controller.overallProgress == 0.5

    def test_warnings_are_kept_on_the_row(self, controller, media):
        controller.addFiles(media[:1])
        controller.startQueue()
        _finish(controller, "job1", outputs=["a.srt"], warnings=["No speech was found."])
        message = controller.fileModel.data(controller.fileModel.index(0), MediaFileModel.MessageRole)
        assert message == "1 file written. Note: No speech was found."

    def test_rejects_files_the_tab_cannot_use(self, controller, tmp_path):
        sub = tmp_path / "x.srt"
        sub.write_text("")
        notices = []
        controller.notice.connect(notices.append)
        controller.addFiles([str(sub)])
        assert controller.fileModel.count == 0
        assert notices == ["Skipped 1 file this tab can't use."]

    def test_file_urls_are_accepted(self, controller, media):
        controller.addFiles(["file:///" + media[0].replace("\\", "/")])
        assert controller.fileModel.count == 1


class TestOptions:
    def test_job_body_uses_options_and_input_folder(self, controller, media):
        controller.setOption("language", "ur")
        controller.setFormat("vtt", True)
        controller.addFiles(media[:1])
        controller.startQueue()
        body = controller._api.jobs()[0]
        assert body["task"] == "generate"
        assert body["language"] == "ur"
        assert body["formats"] == ["srt", "vtt"]
        assert body["output_dir"] == str(media[0]).rsplit("\\", 1)[0]

    def test_unknown_option_is_ignored(self, controller):
        controller.setOption("nope", 1)
        assert "nope" not in controller.options

    def test_saved_preferences_keep_session_changes(self, controller):
        controller.setOption("model_name", "small")
        controller._api.settings = {"model": {"name": "large-v3", "device": "cpu"}}
        controller.reloadDefaults()
        assert controller.options["model_name"] == "small"
        assert controller.options["device"] == "cpu"

    def test_preferences_saved_while_running_apply_afterwards(self, controller, media):
        controller.addFiles(media[:1])
        controller.startQueue()
        controller._api.settings = {"model": {"device": "cpu"}}
        controller.reloadDefaults()
        assert controller.options["device"] == "auto"
        _finish(controller, "job1")
        assert controller.options["device"] == "cpu"

    def test_blocker_comes_from_api_validation(self, controller, media):
        controller.addFiles(media[:1])
        controller._api.errors = ["Select at least one subtitle format."]
        controller._validate()
        assert controller.blocker == "Select at least one subtitle format."
        controller.startQueue()
        assert controller._api.jobs() == []

    def test_empty_queue_blocks(self, controller):
        assert controller.blocker == "Add a video or audio file to the queue first."


def _steps(body):
    """The kinds of a workflow job's steps, in order."""
    return [step["kind"] for step in body["steps"]]


class TestTranslateTab:
    def test_uses_language_handed_over(self, tmp_path):
        ctrl = _make(TranslateController)
        sub = tmp_path / "movie.srt"
        sub.write_text("")
        ctrl.receiveFiles([str(sub)], "", ["en"])
        ctrl.setOption("target_lang", "ur")
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["source_lang"] == "en"

    def test_each_output_keeps_the_language_the_job_reported(self, tmp_path):
        ctrl = _make(TranslateController)
        ctrl.setOption("target_lang", "ur")
        sub = tmp_path / "movie_en.srt"
        sub.write_text("")
        ctrl.addFiles([str(sub)])
        ctrl.startQueue()
        out_ur, out_vtt = str(tmp_path / "movie_ur.srt"), str(tmp_path / "movie_ur.vtt")
        _finish(ctrl, "job1", outputs=[out_ur, out_vtt], output_languages={out_ur: "ur", out_vtt: "ur"})
        assert ctrl.outputLanguage(out_ur) == "ur" and ctrl.outputLanguage(out_vtt) == "ur"

    def test_handed_over_files_keep_their_own_languages(self, tmp_path):
        ctrl = _make(TranslateController)
        first, second = tmp_path / "movie.srt", tmp_path / "movie_tr.srt"
        first.write_text("")
        second.write_text("")
        ctrl.receiveFiles([str(first), str(second)], "", ["en", "ur"])
        assert ctrl.fileModel.item(str(first))["language"] == "en"
        assert ctrl.fileModel.item(str(second))["language"] == "ur"

    def test_subtitle_of_unknown_language_blocks_until_chosen(self, tmp_path):
        ctrl = _make(TranslateController)
        (tmp_path / "movie.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie.srt")])
        assert ctrl.needsSubtitleLanguage
        ctrl._validate()
        assert ctrl.blocker == "Choose the language of movie.srt in the queue."
        assert ctrl._api.posts == []
        ctrl.fileModel.setChosenLanguage(0, "fr")
        ctrl._validate()
        assert ctrl.blocker == ""
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["source_lang"] == "fr"

    def test_chosen_language_overrides_the_file_name(self, tmp_path):
        ctrl = _make(TranslateController)
        ctrl.setOption("target_lang", "ur")
        (tmp_path / "movie.en.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie.en.srt")])
        assert ctrl.fileModel.item(str(tmp_path / "movie.en.srt"))["language"] == "en"
        ctrl.fileModel.setChosenLanguage(0, "es")
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["source_lang"] == "es"

    def test_subtitle_already_in_the_target_blocks(self, tmp_path):
        ctrl = _make(TranslateController)
        ctrl.setOption("target_lang", "en")
        (tmp_path / "movie_en.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_en.srt")])
        ctrl._validate()
        assert ctrl.blocker.startswith("movie_en.srt is already in English.")

    def test_video_is_transcribed_then_translated(self, tmp_path):
        ctrl = _make(TranslateController)
        ctrl.setOption("target_lang", "ur")
        (tmp_path / "talk.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "talk.mp4")])
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert body["task"] == "workflow" and _steps(body) == ["generate", "translate"]
        generate, translate = body["steps"]
        assert generate["write_output"] is False and generate["language"] is None
        assert translate["input"] == "step:0" and translate["source_lang"] == "auto"
        assert translate["target_lang"] == "ur" and translate["write_output"] is True

    def test_spoken_language_is_passed_to_transcription(self, tmp_path):
        ctrl = _make(TranslateController)
        ctrl.setOption("spoken_language", "ja")
        ctrl.setOption("target_lang", "en")
        (tmp_path / "talk.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "talk.mp4")])
        ctrl.startQueue()
        generate, translate = ctrl._api.jobs()[0]["steps"]
        assert generate["language"] == "ja" and translate["source_lang"] == "ja"

    def test_spoken_language_equal_to_the_target_blocks(self, tmp_path):
        ctrl = _make(TranslateController)
        ctrl.setOption("spoken_language", "en")
        ctrl.setOption("target_lang", "en")
        (tmp_path / "talk.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "talk.mp4")])
        ctrl._validate()
        assert ctrl.blocker.startswith("The spoken language is English")


class TestTransliterateTab:
    def test_video_converts_from_the_script_of_the_speech(self, tmp_path):
        ctrl = _make(TransliterateController)
        ctrl.setOption("target_scheme", "roman")
        (tmp_path / "talk.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "talk.mp4")])
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert _steps(body) == ["generate", "transliterate"]
        assert body["steps"][1]["source_scheme"] == "auto"

    def test_explicit_script_needs_no_language(self, tmp_path):
        ctrl = _make(TransliterateController)
        (tmp_path / "song.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "song.srt")])
        assert not ctrl.needsSubtitleLanguage
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["source_scheme"] == "roman"

    def test_automatic_script_follows_the_subtitle_language(self, tmp_path):
        ctrl = _make(TransliterateController)
        ctrl.setOption("source_scheme", "auto")
        ctrl.setOption("target_scheme", "roman")
        (tmp_path / "song.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "song.srt")])
        assert ctrl.needsSubtitleLanguage
        ctrl._validate()
        assert ctrl.blocker == "Choose the language of song.srt in the queue."
        ctrl.fileModel.setChosenLanguage(0, "ur")
        ctrl._validate()
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["source_scheme"] == "ur"

    def test_automatic_script_rejects_text_already_in_the_target(self, tmp_path):
        ctrl = _make(TransliterateController)
        ctrl.setOption("source_scheme", "auto")
        ctrl.setOption("target_scheme", "roman")
        (tmp_path / "song_en.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "song_en.srt")])
        ctrl._validate()
        assert ctrl.blocker.startswith("song_en.srt is already written in that script.")

    def test_automatic_script_rejects_a_language_without_one(self, tmp_path):
        ctrl = _make(TransliterateController)
        ctrl.setOption("source_scheme", "auto")
        (tmp_path / "song_ja.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "song_ja.srt")])
        ctrl._validate()
        assert ctrl.blocker == "Transliteration doesn't support Japanese's script (song_ja.srt)."


def _dub():
    """A Dub tab whose user already accepted the voice cloning licences."""
    ctrl = _make(DubController)
    ctrl._saved_settings = {"dubbing": {"omnivoice_terms_accepted": True, "xtts_terms_accepted": True}}
    return ctrl


class TestDubTab:
    def test_voice_cloning_waits_for_the_licence(self, tmp_path):
        ctrl = _make(DubController)
        (tmp_path / "movie_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        # Automatic resolves to OmniVoice, whose licence comes first.
        assert "OmniVoice licence" in ctrl.blocker
        ctrl.setOption("mode", "xtts")
        assert "XTTS-v2 licence" in ctrl.blocker
        ctrl.setOption("mode", "piper")
        assert ctrl.blocker == ""

    def test_jobs_carry_the_saved_profile(self, tmp_path):
        ctrl = _dub()
        ctrl._saved_settings["performance"] = {"profile": "balanced"}
        (tmp_path / "talk_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk_es.srt")])
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["profile"] == "balanced"

    def test_custom_profile_jobs_carry_the_recommended_profile_and_quality(self, tmp_path):
        ctrl = _dub()
        ctrl._saved_settings["performance"] = {"profile": "custom", "recommended": "balanced"}
        ctrl.setOption("quality", "full")
        (tmp_path / "talk_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk_es.srt")])
        ctrl.startQueue()
        job = ctrl._api.jobs()[0]
        assert job["profile"] == "balanced" and job["steps"][-1]["quality"] == "full"

    def test_video_alone_is_transcribed_translated_and_dubbed(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("language", "es")
        (tmp_path / "movie.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "movie.mp4")])
        ctrl._validate()
        assert not ctrl.blocker.startswith("Choose")
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert body["task"] == "workflow" and "text_path" not in body
        assert _steps(body) == ["generate", "translate", "dub"]
        assert body["steps"][1]["source_lang"] == "auto" and body["steps"][1]["target_lang"] == "es"
        assert body["steps"][2]["input"] == "step:1" and body["steps"][2]["language"] == "es"
        assert body["steps"][2]["output"] == "track"

    def test_translation_is_skipped_when_spoken_in_the_dub_language(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("spoken_language", "es")
        ctrl.setOption("language", "es")
        (tmp_path / "movie.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "movie.mp4")])
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert _steps(body) == ["generate", "dub"] and body["steps"][1]["input"] == "step:0"

    def test_keep_the_spoken_language_never_translates(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("language", "auto")
        (tmp_path / "movie.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "movie.mp4")])
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert _steps(body) == ["generate", "dub"] and body["steps"][1]["language"] == "auto"

    def test_paired_subtitle_is_spoken_instead_of_a_transcript(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("language", "es")
        (tmp_path / "movie.mp4").write_bytes(b"x")
        (tmp_path / "movie_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        assert ctrl.fileModel.getPaths() == [str(tmp_path / "movie.mp4")]
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert body["text_path"] == str(tmp_path / "movie_es.srt") and body["text_language"] == "es"
        assert _steps(body) == ["dub"] and body["steps"][0]["input"] == "source"

    def test_paired_subtitle_in_another_language_is_translated(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("language", "ur")
        (tmp_path / "movie.mp4").write_bytes(b"x")
        (tmp_path / "movie_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert _steps(body) == ["translate", "dub"]
        assert body["steps"][0]["source_lang"] == "es" and body["steps"][0]["write_output"] is False

    def test_transcribe_instead_drops_the_pairing(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "movie.mp4").write_bytes(b"x")
        (tmp_path / "movie_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        ctrl.fileModel.setCompanion(0, "")
        ctrl.startQueue()
        assert _steps(ctrl._api.jobs()[0])[0] == "generate"

    def test_lone_subtitle_becomes_a_wav(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "talk_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk_es.srt")])
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert body["input_path"] == str(tmp_path / "talk_es.srt")
        assert body["steps"][-1]["output"] == "wav"

    def test_subtitle_of_unknown_language_blocks_start(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "talk.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk.srt")])
        ctrl._validate()
        assert ctrl.blocker == "Choose the language of talk.srt in the queue."
        ctrl.fileModel.setChosenLanguage(0, "es")
        ctrl._validate()
        assert ctrl.blocker == ""

    def test_handed_over_subtitle_speaks_for_its_source(self, tmp_path):
        ctrl = _make(DubController)
        (tmp_path / "movie.mp4").write_bytes(b"x")
        (tmp_path / "movie_ur.srt").write_text("")
        ctrl.receiveFiles([str(tmp_path / "movie_ur.srt")], str(tmp_path / "movie.mp4"), ["ur"])
        item = ctrl.fileModel.item(str(tmp_path / "movie.mp4"))
        assert item["companion"] == str(tmp_path / "movie_ur.srt") and item["language"] == "ur"

    def test_many_files_that_cannot_start_fail_without_overflowing_the_stack(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("mode", "piper")
        for index in range(1500):
            (tmp_path / f"clip{index}.srt").write_text("")
        ctrl.addFiles([str(p) for p in tmp_path.iterdir()])
        ctrl.startQueue()
        assert not ctrl.busy
        assert ctrl.summary == "0 of 1500 files done, 1500 failed."

    def test_choosing_another_subtitle_takes_its_language(self, tmp_path):
        ctrl = _dub()
        for name in ("movie.mp4", "movie_es.srt", "movie_fr.srt"):
            (tmp_path / name).write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        ctrl.fileModel.setChosenLanguage(0, "de")
        rechecks = []
        ctrl.fileModel.inputsChanged.connect(lambda: rechecks.append(True))
        ctrl.fileModel.setCompanion(0, str(tmp_path / "movie_fr.srt"))
        item = ctrl.fileModel.item(str(tmp_path / "movie.mp4"))
        assert item["language"] == "fr" and item["chosen_language"] == ""
        assert rechecks and ctrl._validate_timer.isActive()

    def test_changing_mode_or_language_resets_a_chosen_voice(self):
        ctrl = _dub()
        ctrl.setOption("mode", "piper")
        ctrl.setOption("voice", "piper:ur_PK-fasih-medium")
        ctrl.setOption("mode", "kokoro")
        assert ctrl.options["voice"] == "auto"
        ctrl.setOption("voice", "kokoro:af_heart")
        ctrl.setOption("language", "es")
        assert ctrl.options["voice"] == "auto"

    def test_voice_options_follow_mode_and_language(self):
        ctrl = _make(DubController)
        assert len(ctrl.voiceOptions("xtts", "en")) == 1
        assert any(v["code"] == "piper:ur_PK-fasih-medium" for v in ctrl.voiceOptions("piper", "ur"))
