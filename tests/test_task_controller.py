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
    find_companion,
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


class TestTranslateTab:
    def test_detect_uses_language_handed_over(self, tmp_path):
        ctrl = _make(TranslateController)
        sub = tmp_path / "movie.srt"
        sub.write_text("")
        ctrl.receiveFiles([str(sub)], "", ["en"])
        ctrl.setOption("target_lang", "ur")
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["source_lang"] == "en"

    def test_each_output_keeps_the_language_the_job_reported(self, tmp_path):
        ctrl = _make(TranslateController)
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

    def test_detect_blocks_a_file_of_unknown_language(self, tmp_path):
        ctrl = _make(TranslateController)
        (tmp_path / "movie.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie.srt")])
        ctrl._validate()
        assert ctrl.blocker.startswith("movie.srt has no language in its name.")
        assert ctrl._api.posts == []
        ctrl.setOption("source_lang", "en")
        ctrl._validate()
        assert ctrl.blocker == ""


def _dub():
    """A Dub tab whose user already accepted the voice cloning licence."""
    ctrl = _make(DubController)
    ctrl._saved_settings = {"dubbing": {"xtts_terms_accepted": True}}
    return ctrl


class TestDubTab:
    def test_voice_cloning_waits_for_the_licence(self, tmp_path):
        ctrl = _make(DubController)
        (tmp_path / "movie_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        assert "XTTS-v2 licence" in ctrl.blocker
        ctrl.setOption("mode", "piper")
        assert ctrl.blocker == ""

    def test_subtitle_pairs_with_its_media(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "movie.mp4").write_bytes(b"x")
        (tmp_path / "movie_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        assert ctrl.fileModel.getPaths() == [str(tmp_path / "movie.mp4")]
        ctrl.startQueue()
        body = ctrl._api.jobs()[0]
        assert body["subtitle_path"] == str(tmp_path / "movie_es.srt")
        assert body["language"] == "es"

    def test_urdu_script_bridge_follows_preferences_into_the_job(self, tmp_path):
        ctrl = _dub()
        assert ctrl.options["script_bridge"] is True
        ctrl._apply_defaults({"dubbing": {"script_bridge": False}})
        (tmp_path / "talk_ur.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk_ur.srt")])
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["script_bridge"] is False

    def test_lone_subtitle_becomes_a_wav(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "talk_es.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk_es.srt")])
        ctrl.startQueue()
        assert ctrl._api.jobs()[0]["output"] == "wav"

    def test_media_without_subtitle_fails_with_a_reason(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "movie.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "movie.mp4")])
        ctrl.startQueue()
        assert ctrl._api.jobs() == []
        message = ctrl.fileModel.data(ctrl.fileModel.index(0), MediaFileModel.MessageRole)
        assert message.startswith("No subtitle found for movie.mp4")

    def test_media_without_subtitle_blocks_start(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "movie.mp4").write_bytes(b"x")
        ctrl.addFiles([str(tmp_path / "movie.mp4")])
        ctrl._validate()
        assert ctrl.blocker.startswith("No subtitle found for movie.mp4")

    def test_choosing_a_subtitle_rechecks_the_queue(self, tmp_path):
        ctrl = _dub()
        for name in ("movie.mp4", "movie_es.srt", "movie_fr.srt"):
            (tmp_path / name).write_text("")
        ctrl.addFiles([str(tmp_path / "movie.mp4")])
        ctrl._validate()
        assert "has several subtitles" in ctrl.blocker
        rechecks = []
        ctrl.fileModel.inputsChanged.connect(lambda: rechecks.append(True))
        ctrl.fileModel.setCompanion(0, str(tmp_path / "movie_fr.srt"))
        assert rechecks and ctrl._validate_timer.isActive()
        ctrl._validate()
        assert ctrl.blocker == ""

    def test_subtitle_of_unknown_language_blocks_start(self, tmp_path):
        ctrl = _dub()
        (tmp_path / "talk.srt").write_text("")
        ctrl.addFiles([str(tmp_path / "talk.srt")])
        ctrl._validate()
        assert ctrl.blocker.startswith("talk.srt has no language in its name.")
        ctrl.setOption("language", "es")
        ctrl._validate()
        assert ctrl.blocker == ""

    def test_handed_over_subtitle_speaks_for_its_source(self, tmp_path):
        ctrl = _make(DubController)
        (tmp_path / "movie.mp4").write_bytes(b"x")
        (tmp_path / "movie_ur.srt").write_text("")
        ctrl.receiveFiles([str(tmp_path / "movie_ur.srt")], str(tmp_path / "movie.mp4"), ["ur"])
        item = ctrl.fileModel.item(str(tmp_path / "movie.mp4"))
        assert item["companion"] == str(tmp_path / "movie_ur.srt") and item["language"] == "ur"

    def test_many_files_without_subtitles_fail_without_overflowing_the_stack(self, tmp_path):
        ctrl = _dub()
        ctrl.setOption("mode", "piper")
        for index in range(1500):
            (tmp_path / f"clip{index}.mp4").write_bytes(b"")
        ctrl.addFiles([str(p) for p in tmp_path.iterdir()])
        ctrl.startQueue()
        assert not ctrl.busy
        assert ctrl.summary == "0 of 1500 files done, 1500 failed."

    def test_choosing_another_subtitle_takes_its_language(self, tmp_path):
        ctrl = _dub()
        for name in ("movie.mp4", "movie_es.srt", "movie_fr.srt"):
            (tmp_path / name).write_text("")
        ctrl.addFiles([str(tmp_path / "movie_es.srt")])
        ctrl.fileModel.setCompanion(0, str(tmp_path / "movie_fr.srt"))
        assert ctrl.fileModel.item(str(tmp_path / "movie.mp4"))["language"] == "fr"

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


class TestFindCompanion:
    def test_prefers_the_chosen_language(self, tmp_path):
        for name in ("m.mp4", "m_es.srt", "m_ur.srt"):
            (tmp_path / name).write_text("")
        assert find_companion(str(tmp_path / "m.mp4"), "ur").endswith("m_ur.srt")

    def test_single_candidate_is_used(self, tmp_path):
        for name in ("m.mp4", "m.srt", "other_es.srt"):
            (tmp_path / name).write_text("")
        assert find_companion(str(tmp_path / "m.mp4"), "auto").endswith("m.srt")

    def test_several_candidates_need_a_choice(self, tmp_path):
        for name in ("m.mp4", "m_es.srt", "m_ur.srt"):
            (tmp_path / name).write_text("")
        with pytest.raises(ValueError, match="several subtitles"):
            find_companion(str(tmp_path / "m.mp4"), "auto")
