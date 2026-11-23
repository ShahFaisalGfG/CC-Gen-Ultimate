# test_api_assets.py - tests for the Manage Models list/download/cancel/remove routes and stream

import errno
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ccgen.api.app import app
from ccgen.core.errors import disk_full_message

_CATALOG = [
    {
        "id": "whisper:tiny", "category": "whisper", "engine": "Whisper", "label": "tiny",
        "name": "Whisper tiny", "downloaded": False, "size_bytes": None, "approx_size_mb": 75,
    },
]


@pytest.fixture
def client():
    """A TestClient kept open for the whole test so asset_manager's worker task survives."""
    with TestClient(app) as c:
        yield c


def _collect_until_finished(ws, limit=10):
    """Read websocket JSON events until a 'finished' event arrives, or bail after limit reads."""
    events = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event.get("event") == "finished":
            break
    return events


class TestListAssets:
    def test_returns_catalog_from_registry(self, client):
        with patch("ccgen.api.services.asset_manager.asset_registry.list_assets", return_value=_CATALOG):
            resp = client.get("/assets")
        assert resp.status_code == 200
        assert resp.json() == _CATALOG


class TestDownloadAsset:
    def test_queues_and_streams_to_finished(self, client):
        with patch("ccgen.api.services.asset_manager.asset_registry.download_asset") as mock_download:
            with client.websocket_connect("/assets/stream") as ws:
                resp = client.post("/assets/test:download-happy/download")
                assert resp.status_code == 200
                assert resp.json() == {"queued": True}
                events = _collect_until_finished(ws)

        assert [e["event"] for e in events] == ["queued", "finished"]
        assert events[-1] == {"event": "finished", "id": "test:download-happy", "success": True, "error": ""}
        mock_download.assert_called_once()
        assert mock_download.call_args.args[0] == "test:download-happy"

    def test_failed_download_reports_a_plain_error_on_stream(self, client):
        with patch(
            "ccgen.api.services.asset_manager.asset_registry.download_asset",
            side_effect=OSError(errno.ENOSPC, "No space left on device"),
        ):
            with client.websocket_connect("/assets/stream") as ws:
                client.post("/assets/test:download-fails/download")
                events = _collect_until_finished(ws)

        finished = events[-1]
        assert finished["success"] is False
        assert finished["error"] == disk_full_message()

    def test_an_unexplained_failure_says_what_to_do(self, client):
        with patch(
            "ccgen.api.services.asset_manager.asset_registry.download_asset",
            side_effect=RuntimeError("network unreachable"),
        ):
            with client.websocket_connect("/assets/stream") as ws:
                client.post("/assets/test:download-odd/download")
                events = _collect_until_finished(ws)

        error = events[-1]["error"]
        assert "network unreachable" not in error
        assert error.startswith("The download stopped") and "Preferences > Advanced" in error

    def test_progress_and_status_events_are_forwarded(self, client):
        def fake_download(asset_id, status_cb, progress_num_cb, cancel_check):
            status_cb("Downloading...")
            progress_num_cb(1, 2)

        with patch(
            "ccgen.api.services.asset_manager.asset_registry.download_asset", side_effect=fake_download
        ):
            with client.websocket_connect("/assets/stream") as ws:
                client.post("/assets/test:download-progress/download")
                events = _collect_until_finished(ws)

        kinds = [e["event"] for e in events]
        assert kinds == ["queued", "status", "progress", "finished"]
        assert events[2] == {"event": "progress", "id": "test:download-progress", "done": 1, "total": 2}


class TestCancelAsset:
    def test_cancels_a_queued_download_before_it_starts(self, client):
        first_can_finish = threading.Event()

        def blocking_download(asset_id, status_cb, progress_num_cb, cancel_check):
            first_can_finish.wait(timeout=5)

        with patch(
            "ccgen.api.services.asset_manager.asset_registry.download_asset",
            side_effect=blocking_download,
        ):
            with client.websocket_connect("/assets/stream") as ws:
                client.post("/assets/test:cancel-first/download")
                assert ws.receive_json() == {"event": "queued", "id": "test:cancel-first"}

                client.post("/assets/test:cancel-second/download")
                assert ws.receive_json() == {"event": "queued", "id": "test:cancel-second"}

                cancel_resp = client.post("/assets/test:cancel-second/cancel")
                assert cancel_resp.json() == {"cancelled": True}
                # Dropped from the queue before the worker reached it, and reported at once, so
                # the app stops showing it as queued (and stops counting it as busy).
                assert ws.receive_json() == {
                    "event": "finished", "id": "test:cancel-second", "success": False, "error": "Cancelled",
                }

                first_can_finish.set()
                events = _collect_until_finished(ws)

        assert [e["event"] for e in events] == ["finished"]
        assert events[0]["id"] == "test:cancel-first"

    def test_unknown_asset_returns_not_cancelled(self, client):
        resp = client.post("/assets/test:never-queued/cancel")
        assert resp.json() == {"cancelled": False}

    def test_cancels_a_download_already_in_progress(self, client):
        started = threading.Event()

        def slow_download(asset_id, status_cb, progress_num_cb, cancel_check):
            started.set()
            for _ in range(50):
                if cancel_check():
                    raise RuntimeError("cancelled mid-transfer")
                time.sleep(0.05)

        with patch(
            "ccgen.api.services.asset_manager.asset_registry.download_asset",
            side_effect=slow_download,
        ):
            with client.websocket_connect("/assets/stream") as ws:
                client.post("/assets/test:cancel-active/download")
                assert ws.receive_json() == {"event": "queued", "id": "test:cancel-active"}
                assert started.wait(timeout=5)

                cancel_resp = client.post("/assets/test:cancel-active/cancel")
                assert cancel_resp.json() == {"cancelled": True}

                events = _collect_until_finished(ws)

        assert events[-1] == {
            "event": "finished", "id": "test:cancel-active", "success": False, "error": "Cancelled",
        }


class TestRemoveAsset:
    def test_removes_via_registry(self, client):
        with patch("ccgen.api.services.asset_manager.asset_registry.delete_asset") as mock_delete:
            resp = client.delete("/assets/test:remove-me")
        assert resp.status_code == 200
        assert resp.json() == {"removed": True}
        mock_delete.assert_called_once_with("test:remove-me")

    def test_registry_failure_returns_400_with_a_plain_sentence(self, client):
        error = PermissionError(errno.EACCES, "Access is denied", "model.bin")
        with patch("ccgen.api.services.asset_manager.asset_registry.delete_asset", side_effect=error):
            resp = client.delete("/assets/test:remove-fails")
        assert resp.status_code == 400
        assert resp.json()["detail"].startswith("Windows didn't allow access to model.bin.")

    def test_an_unexplained_removal_failure_says_what_to_do(self, client):
        with patch(
            "ccgen.api.services.asset_manager.asset_registry.delete_asset",
            side_effect=RuntimeError("in use"),
        ):
            resp = client.delete("/assets/test:remove-odd")
        assert resp.status_code == 400
        assert resp.json()["detail"].startswith("Close any task that uses the model")
