# test_assets_ctrl.py - the Manage Models controller's download state (no API server)

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.controllers import assets_ctrl


class _FakeApi:
    """Stands in for ApiClient: no server, no stream; the test feeds stream events directly."""

    def __init__(self, base_url, parent=None):
        self.base_url = base_url

    def open_stream(self, path, handler):
        return None

    def get(self, path, handler):
        pass


@pytest.fixture
def controller(monkeypatch):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    monkeypatch.setattr(assets_ctrl, "ApiClient", _FakeApi)
    return assets_ctrl.AssetsController("http://127.0.0.1:1")


def test_busy_while_any_download_is_queued_or_running(controller):
    """Installing an update waits for model downloads (UpdateController's busy sources)."""
    changes: list[bool] = []
    controller.busyChanged.connect(changes.append)
    assert controller.busy is False
    controller._on_stream_event({"event": "queued", "id": "whisper-small"})
    controller._on_stream_event({"event": "queued", "id": "piper-en"})
    controller._on_stream_event({"event": "finished", "id": "whisper-small", "success": True})
    assert controller.busy is True
    controller._on_stream_event({"event": "finished", "id": "piper-en", "success": False, "error": "cancelled"})
    assert controller.busy is False
    assert changes == [True, False]
