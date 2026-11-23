# test_api_jobs.py - tests for job validate/start/poll/cancel routes and the live event websocket

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ccgen.api.app import app
from ccgen.core.tasks import TaskResult

_SEGMENT = {"id": 0, "start": 0.0, "end": 1.0, "text": "hi", "words": [], "language": "en"}


@pytest.fixture
def client():
    """A TestClient kept open for the whole test so job_manager's background task survives."""
    with TestClient(app) as c:
        yield c


def _body(tmp_path, name="video.mp4", **extra):
    """Build a generate job body pointing at a path the mocked task never reads."""
    return {"task": "generate", "input_path": str(tmp_path / name), **extra}


def _start_job(client, tmp_path, name="video.mp4"):
    """Post a job and return its job_id, asserting the request succeeded."""
    resp = client.post("/jobs", json=_body(tmp_path, name))
    assert resp.status_code == 200, resp.text
    return resp.json()["job_id"]


def _default_run(status_cb, segment_cb, progress_cb):
    """Fast stand-in for Task.run() used when a test does not care about callbacks."""
    return TaskResult(success=True, input_path="in.mp4", output_files=[])


def _fake_task(prepare_side_effect=None, run_side_effect=None):
    """Build a fake task whose methods invoke the callbacks job_manager passes in."""
    task = MagicMock()
    task.cancelled = False
    task.stage, task.step, task.stages = "transcribe", 1, ["load", "transcribe"]
    task.config = SimpleNamespace(input_path="in.mp4")
    task.cancel.side_effect = lambda: setattr(task, "cancelled", True)
    task.prepare.side_effect = prepare_side_effect or (lambda status_cb, progress_cb: None)
    task.run.side_effect = run_side_effect or _default_run
    return task


def _patched(*tasks):
    """Patch create_task to hand out the given fake tasks in order."""
    return patch("ccgen.api.services.job_manager.create_task", side_effect=list(tasks))


def _collect_until_finished(ws, limit=10):
    """Read websocket JSON events until a 'finished' event arrives, or bail after limit reads."""
    events = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event.get("event") == "finished":
            break
    return events


class TestValidateJob:
    def test_valid_body_has_no_errors(self, client, tmp_path):
        assert client.post("/jobs/validate", json=_body(tmp_path)).json() == {"errors": []}

    def test_reports_readable_messages(self, client, tmp_path):
        body = _body(tmp_path, formats=[])
        assert client.post("/jobs/validate", json=body).json() == {
            "errors": ["Select at least one subtitle format."],
        }

    def test_rejects_subtitle_input_for_generation(self, client, tmp_path):
        errors = client.post("/jobs/validate", json=_body(tmp_path, "movie.srt")).json()["errors"]
        assert errors == ["Subtitle generation needs a video or audio file, not a subtitle file."]

    def test_rejects_unknown_task(self, client, tmp_path):
        errors = client.post("/jobs/validate", json={"task": "nope", "input_path": "x"}).json()["errors"]
        assert len(errors) == 1 and "nope" in errors[0]

    def test_translation_needs_different_languages(self, client, tmp_path):
        body = {"task": "translate", "input_path": str(tmp_path / "a.srt"), "source_lang": "en", "target_lang": "en"}
        assert client.post("/jobs/validate", json=body).json()["errors"] == [
            "Choose a target language different from the source language.",
        ]

    def test_transliteration_checks_engine_support(self, client, tmp_path):
        body = {
            "task": "transliterate", "input_path": str(tmp_path / "a.srt"),
            "source_scheme": "ta", "target_scheme": "ur", "engine": "neural",
        }
        assert client.post("/jobs/validate", json=body).json()["errors"] == [
            "The neural engine can't convert ta to ur.",
        ]


class TestStartJob:
    def test_returns_job_id(self, client, tmp_path):
        with _patched(_fake_task()):
            job_id = _start_job(client, tmp_path)
        assert isinstance(job_id, str) and job_id

    def test_invalid_body_returns_400_with_reason(self, client, tmp_path):
        resp = client.post("/jobs", json=_body(tmp_path, formats=[]))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Select at least one subtitle format."

    def test_missing_input_path_returns_400(self, client):
        resp = client.post("/jobs", json={"task": "generate"})
        assert resp.status_code == 400
        assert "input_path" in resp.json()["detail"]


class TestGetJob:
    def test_unknown_id_returns_404(self, client):
        assert client.get("/jobs/does-not-exist").status_code == 404

    def test_busy_then_completed_shape(self, client, tmp_path):
        run_can_finish = threading.Event()

        def blocking_run(status_cb, segment_cb, progress_cb):
            segment_cb(_SEGMENT)
            progress_cb(1, 1)
            run_can_finish.wait(timeout=5)
            return TaskResult(success=True, input_path="in.mp4", output_files=["out.srt"], warnings=["w"])

        with _patched(_fake_task(run_side_effect=blocking_run)):
            job_id = _start_job(client, tmp_path)
            assert client.get(f"/jobs/{job_id}").json() == {"job_id": job_id, "busy": True}

            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                run_can_finish.set()
                events = _collect_until_finished(ws)

        assert events[-1]["event"] == "finished"
        assert client.get(f"/jobs/{job_id}").json() == {
            "job_id": job_id, "busy": False, "success": True,
            "error": "", "error_detail": "", "output_files": ["out.srt"], "warnings": ["w"],
        }


class TestStreamJob:
    def test_events_carry_stage_and_finish_with_details(self, client, tmp_path):
        def fake_run(status_cb, segment_cb, progress_cb):
            segment_cb(_SEGMENT)
            progress_cb(1, 4)
            return TaskResult(
                success=True, input_path="in.mp4", output_files=["out.srt"],
                detected_language="en", warnings=["No speech"], output_languages={"out.srt": "en"},
            )

        with _patched(_fake_task(run_side_effect=fake_run)):
            job_id = _start_job(client, tmp_path)
            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                events = _collect_until_finished(ws)

        assert [e["event"] for e in events] == ["segment", "progress", "finished"]
        assert events[0] == {
            "event": "segment", "kind": "transcript", "stage": "transcribe", "step": 1,
            "id": 0, "start": 0.0, "end": 1.0, "text": "hi",
        }
        assert events[1] == {
            "event": "progress", "done": 1, "total": 4, "stage": "transcribe", "step": 1, "steps": 2,
        }
        assert events[2] == {
            "event": "finished", "success": True, "error": "", "error_detail": "", "error_kind": "", "cancelled": False,
            "output_files": ["out.srt"], "detected_language": "en", "warnings": ["No speech"],
            "output_languages": {"out.srt": "en"},
        }

    def test_translation_segments_are_labelled(self, client, tmp_path):
        def fake_run(status_cb, segment_cb, progress_cb):
            segment_cb({"id": 3, "start": 0.0, "end": 1.0, "original": "hi", "translated": "hola", "language": "es"})
            return TaskResult(success=True, input_path="in.mp4")

        with _patched(_fake_task(run_side_effect=fake_run)):
            job_id = _start_job(client, tmp_path)
            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                events = _collect_until_finished(ws)

        assert events[0]["kind"] == "translation" and events[0]["text"] == "hola"


class TestSerializedRuns:
    def test_second_job_waits_for_the_first(self, client, tmp_path):
        first_can_finish = threading.Event()
        order: list[str] = []

        def first_run(status_cb, segment_cb, progress_cb):
            order.append("first-start")
            first_can_finish.wait(timeout=5)
            order.append("first-end")
            return TaskResult(success=True, input_path="a.mp4")

        def second_run(status_cb, segment_cb, progress_cb):
            order.append("second-start")
            return TaskResult(success=True, input_path="b.mp4")

        with _patched(_fake_task(run_side_effect=first_run), _fake_task(run_side_effect=second_run)):
            first = _start_job(client, tmp_path, "a.mp4")
            second = _start_job(client, tmp_path, "b.mp4")
            with client.websocket_connect(f"/jobs/{second}/stream") as ws:
                waiting = ws.receive_json()
                first_can_finish.set()
                second_events = _collect_until_finished(ws)
            with client.websocket_connect(f"/jobs/{first}/stream") as ws:
                _collect_until_finished(ws)

        assert waiting == {
            "event": "status", "message": "Waiting for another task to finish...",
            "stage": "transcribe", "step": 1, "steps": 2,
        }
        assert second_events[-1]["success"] is True
        assert order == ["first-start", "first-end", "second-start"]

    def test_cancelling_a_waiting_job_never_prepares_it(self, client, tmp_path):
        first_can_finish = threading.Event()

        def first_run(status_cb, segment_cb, progress_cb):
            first_can_finish.wait(timeout=5)
            return TaskResult(success=True, input_path="a.mp4")

        waiting_task = _fake_task()
        with _patched(_fake_task(run_side_effect=first_run), waiting_task):
            first = _start_job(client, tmp_path, "a.mp4")
            second = _start_job(client, tmp_path, "b.mp4")
            assert client.post(f"/jobs/{second}/cancel").json() == {"cancelled": True}
            first_can_finish.set()
            with client.websocket_connect(f"/jobs/{second}/stream") as ws:
                events = _collect_until_finished(ws)
            with client.websocket_connect(f"/jobs/{first}/stream") as ws:
                _collect_until_finished(ws)

        assert events[-1]["cancelled"] is True
        waiting_task.prepare.assert_not_called()

    def test_cancelled_waiting_job_finishes_without_waiting_its_turn(self, client, tmp_path):
        first_can_finish = threading.Event()

        def first_run(status_cb, segment_cb, progress_cb):
            first_can_finish.wait(timeout=10)
            return TaskResult(success=True, input_path="a.mp4")

        with _patched(_fake_task(run_side_effect=first_run), _fake_task()):
            first = _start_job(client, tmp_path, "a.mp4")
            second = _start_job(client, tmp_path, "b.mp4")
            with client.websocket_connect(f"/jobs/{second}/stream") as ws:
                assert ws.receive_json()["message"] == "Waiting for another task to finish..."
                client.post(f"/jobs/{second}/cancel")
                finished = ws.receive_json()
            # The first job is still running: the cancelled one didn't wait for the run slot.
            assert not first_can_finish.is_set()
            first_can_finish.set()
            with client.websocket_connect(f"/jobs/{first}/stream") as ws:
                assert _collect_until_finished(ws)[-1]["success"] is True
        assert finished["event"] == "finished" and finished["cancelled"] is True


class TestCancelJob:
    def test_unknown_id_returns_404(self, client):
        assert client.post("/jobs/does-not-exist/cancel").status_code == 404

    def test_cancel_before_run_reports_cancelled(self, client, tmp_path):
        prepare_can_finish = threading.Event()

        def blocking_prepare(status_cb, progress_cb):
            prepare_can_finish.wait(timeout=5)

        def unexpected_run(*args, **kwargs):
            raise AssertionError("task.run() must not run for a job cancelled before it")

        task = _fake_task(prepare_side_effect=blocking_prepare, run_side_effect=unexpected_run)
        with _patched(task):
            job_id = _start_job(client, tmp_path)

            cancel_resp = client.post(f"/jobs/{job_id}/cancel")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json() == {"cancelled": True}
            prepare_can_finish.set()

            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                finished = ws.receive_json()

        assert finished["event"] == "finished"
        assert finished["success"] is False and finished["cancelled"] is True
        assert finished["error"] == "Cancelled by user."
        task.run.assert_not_called()

    def test_cancel_during_run_signals_the_task(self, client, tmp_path):
        run_started = threading.Event()

        def cancellable_run(status_cb, segment_cb, progress_cb):
            run_started.set()
            for _ in range(500):
                if task.cancelled:
                    return TaskResult(success=False, input_path="in.mp4", error="Cancelled by user.", cancelled=True)
                threading.Event().wait(0.01)
            raise AssertionError("cancel never reached the running task")

        task = _fake_task(run_side_effect=cancellable_run)
        with _patched(task):
            job_id = _start_job(client, tmp_path)
            assert run_started.wait(timeout=5)
            assert client.post(f"/jobs/{job_id}/cancel").json() == {"cancelled": True}
            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                events = _collect_until_finished(ws)

        assert events[-1]["error"] == "Cancelled by user."
        task.cancel.assert_called_once()

    def test_failing_prepare_reports_its_error(self, client, tmp_path):
        def failing_prepare(status_cb, progress_cb):
            raise RuntimeError("Max retries exceeded with url: /Systran/faster-whisper-tiny")

        with _patched(_fake_task(prepare_side_effect=failing_prepare)):
            job_id = _start_job(client, tmp_path)
            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                events = _collect_until_finished(ws)

        # The error reads in plain words with the next step; the library's text is kept as the detail.
        assert events[-1]["success"] is False
        assert events[-1]["error"].startswith("The model couldn't be downloaded. Check the internet connection")
        assert "Max retries exceeded" in events[-1]["error_detail"]


class TestReleaseModels:
    def test_releases_when_idle(self, client):
        with patch("ccgen.api.services.job_manager.model_cache.release_all") as release_all:
            assert client.post("/jobs/release-models").json() == {"released": True}
        release_all.assert_called_once()

    def test_refused_while_job_running(self, client, tmp_path):
        run_can_finish = threading.Event()

        def blocking_run(status_cb, segment_cb, progress_cb):
            run_can_finish.wait(timeout=5)
            return TaskResult(success=True, input_path="in.mp4")

        with _patched(_fake_task(run_side_effect=blocking_run)):
            job_id = _start_job(client, tmp_path)
            with patch("ccgen.api.services.job_manager.model_cache.release_all") as release_all:
                assert client.post("/jobs/release-models").json() == {"released": False}
            release_all.assert_not_called()
            run_can_finish.set()
            with client.websocket_connect(f"/jobs/{job_id}/stream") as ws:
                _collect_until_finished(ws)
