# test_assets_ctrl.py - the Manage Models controller: download state, the list models' per-row
# updates, the busy text, download speed, and failures (no API server)

import pytest
from PySide6.QtCore import QCoreApplication, Qt

from ccgen.controllers import assets_ctrl
from ccgen.controllers.assets_ctrl import AssetRowModel, row_view

_CATALOG = [
    {"id": "whisper:tiny", "category": "whisper", "engine": "Whisper", "label": "tiny", "name": "Whisper tiny",
     "downloaded": True, "size_bytes": 78_000_000, "approx_size_mb": 75},
    {"id": "whisper:small", "category": "whisper", "engine": "Whisper", "label": "small", "name": "Whisper small",
     "downloaded": False, "size_bytes": None, "approx_size_mb": 1000},
    {"id": "whisper:medium", "category": "whisper", "engine": "Whisper", "label": "medium",
     "name": "Whisper medium", "downloaded": False, "size_bytes": None, "approx_size_mb": 1500},
    {"id": "voices:kokoro", "category": "voices", "engine": "Natural voices (Kokoro)",
     "label": "Kokoro model and all voices", "name": "the Kokoro voices", "downloaded": False,
     "size_bytes": None, "approx_size_mb": 354},
]


class _FakeApi:
    """Stands in for ApiClient: no server, no stream; the test feeds stream events directly."""

    def __init__(self, base_url, parent=None):
        self.base_url = base_url
        self.calls: list[tuple[str, str]] = []
        self.handlers: dict[str, object] = {}

    def open_stream(self, path, handler):
        return None

    def get(self, path, handler):
        self.calls.append(("get", path))

    def post(self, path, body=None, handler=None):
        self.calls.append(("post", path))

    def delete(self, path, handler):
        self.calls.append(("delete", path))
        self.handlers[path] = handler


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def controller(monkeypatch, clock):
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    monkeypatch.setattr(assets_ctrl, "ApiClient", _FakeApi)
    ctrl = assets_ctrl.AssetsController("http://127.0.0.1:1", clock=clock)
    ctrl._on_assets([dict(asset) for asset in _CATALOG], "")
    return ctrl


def _role(model, row, name):
    roles = {bytes(value).decode(): key for key, value in model.roleNames().items()}
    return model.data(model.index(row), roles[name])


def _whisper_rows(controller) -> AssetRowModel:
    groups = controller.groups("whisper")
    assert groups.rowCount() == 1
    return _role(groups, 0, "rows")


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


class TestListModels:
    def test_tabs_group_their_models_by_engine(self, controller):
        groups = controller.groups("whisper")
        assert _role(groups, 0, "engine") == "Whisper"
        assert _role(groups, 0, "total") == 3
        assert _role(groups, 0, "downloadedCount") == 1
        assert _role(groups, 0, "downloadIds") == ["whisper:small", "whisper:medium"]
        assert _role(groups, 0, "removeIds") == ["whisper:tiny"]
        assert _role(controller.groups("voices"), 0, "engine") == "Natural voices (Kokoro)"

    def test_progress_changes_only_its_own_row(self, controller):
        """Rows are never rebuilt during a download, so keyboard focus and a screen reader's place stay."""
        rows = _whisper_rows(controller)
        resets: list[bool] = []
        changed: list[tuple[int, int]] = []
        rows.modelReset.connect(lambda: resets.append(True))
        rows.dataChanged.connect(lambda first, last, _roles: changed.append((first.row(), last.row())))
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        controller._on_stream_event({"event": "status", "id": "whisper:small", "message": "Downloading..."})
        controller._on_stream_event({"event": "progress", "id": "whisper:small", "done": 250_000_000, "total": 0})
        assert resets == []
        assert changed and set(changed) == {(1, 1)}
        assert _role(rows, 1, "downloadState") == "downloading"
        assert _role(rows, 1, "progressText") == "25%"
        assert _role(rows, 1, "fraction") == pytest.approx(0.25)

    def test_a_catalog_refresh_updates_rows_in_place(self, controller):
        rows = _whisper_rows(controller)
        resets: list[bool] = []
        rows.modelReset.connect(lambda: resets.append(True))
        catalog = [dict(asset) for asset in _CATALOG]
        catalog[1].update(downloaded=True, size_bytes=486_000_000)
        controller._on_assets(catalog, "")
        assert resets == []
        assert _role(rows, 1, "downloaded") is True
        assert _role(rows, 1, "sizeText") == "486 MB"
        assert _role(controller.groups("whisper"), 0, "downloadedCount") == 2

    def test_sizes_read_as_on_disk_or_about_the_download(self, controller):
        rows = _whisper_rows(controller)
        assert _role(rows, 0, "sizeText") == "78 MB"
        assert _role(rows, 2, "sizeText") == "about 1.5 GB"
        assert controller.usedText == "78 MB"
        assert controller.downloadedIds == ["whisper:tiny"]


class TestDownloadProgress:
    def test_speed_is_measured_over_a_second_or_more(self, controller, clock):
        rows = _whisper_rows(controller)
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        controller._on_stream_event({"event": "status", "id": "whisper:small", "message": "Downloading..."})
        clock.now += 0.5
        controller._on_stream_event({"event": "progress", "id": "whisper:small", "done": 100_000_000, "total": 0})
        assert _role(rows, 1, "progressText") == "10%"
        clock.now += 1.5
        controller._on_stream_event({"event": "progress", "id": "whisper:small", "done": 400_000_000, "total": 0})
        assert _role(rows, 1, "progressText") == "40% · 200.0 MB/s"

    def test_a_download_past_its_size_is_finishing(self, controller):
        rows = _whisper_rows(controller)
        controller._on_stream_event({"event": "progress", "id": "whisper:small", "done": 1_000_000_000,
                                     "total": 1_000_000_000})
        assert _role(rows, 1, "progressText") == "Finishing"
        assert _role(rows, 1, "indeterminate") is True

    def test_busy_text_names_the_download_and_what_waits(self, controller, clock):
        texts: list[str] = []
        controller.busyTextChanged.connect(lambda: texts.append(controller.busyText))
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        assert controller.busyText == "Waiting to download Whisper small"
        controller._on_stream_event({"event": "queued", "id": "voices:kokoro"})
        assert controller.busyText == "Waiting to download 2 models"
        controller._on_stream_event({"event": "progress", "id": "whisper:small", "done": 420_000_000, "total": 0})
        assert controller.busyText == "Downloading Whisper small, 42% (1 more waiting)"
        controller._on_stream_event({"event": "finished", "id": "whisper:small", "success": True, "error": ""})
        controller._on_stream_event({"event": "status", "id": "voices:kokoro", "message": "Downloading..."})
        assert controller.busyText == "Downloading the Kokoro voices"
        controller._on_stream_event({"event": "finished", "id": "voices:kokoro", "success": True, "error": ""})
        assert controller.busyText == ""
        assert texts[-1] == ""

    def test_a_finished_download_shows_as_downloaded_before_the_refresh(self, controller):
        rows = _whisper_rows(controller)
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        controller._on_stream_event({"event": "finished", "id": "whisper:small", "success": True, "error": ""})
        assert _role(rows, 1, "downloaded") is True
        assert _role(rows, 1, "downloadState") == "idle"
        assert ("get", "/assets") in controller._api.calls


class TestFailures:
    def test_a_failure_stays_on_its_row_until_tried_again(self, controller):
        rows = _whisper_rows(controller)
        message = "The model couldn't be downloaded. Check the internet connection and try again."
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        controller._on_stream_event({"event": "finished", "id": "whisper:small", "success": False, "error": message})
        assert _role(rows, 1, "downloadState") == "failed"
        assert _role(rows, 1, "error") == message
        # "Download all" includes it again; Try again queues it like any download.
        assert "whisper:small" in _role(controller.groups("whisper"), 0, "downloadIds")
        controller.downloadAsset("whisper:small")
        assert ("post", "/assets/whisper:small/download") in controller._api.calls
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        assert _role(rows, 1, "downloadState") == "queued"
        assert _role(rows, 1, "error") == ""

    def test_cancel_leaves_the_row_as_it_was(self, controller):
        rows = _whisper_rows(controller)
        controller._on_stream_event({"event": "queued", "id": "whisper:small"})
        controller._on_stream_event({"event": "finished", "id": "whisper:small", "success": False,
                                     "error": "Cancelled"})
        assert _role(rows, 1, "downloadState") == "idle"
        assert _role(rows, 1, "error") == ""
        assert controller.busy is False

    def test_a_failure_is_forgotten_once_the_model_is_there(self, controller):
        rows = _whisper_rows(controller)
        controller._on_stream_event({"event": "finished", "id": "whisper:small", "success": False, "error": "x"})
        catalog = [dict(asset) for asset in _CATALOG]
        catalog[1].update(downloaded=True, size_bytes=1)
        controller._on_assets(catalog, "")
        assert _role(rows, 1, "downloadState") == "idle"
        assert "whisper:small" not in controller._live

    def test_a_failed_removal_names_the_model(self, controller):
        messages: list[tuple[str, str]] = []
        controller.removeFailed.connect(lambda asset_id, message: messages.append((asset_id, message)))
        controller.removeAsset("whisper:tiny")
        controller._api.handlers["/assets/whisper:tiny"](None, "model.bin is open in another app.")
        assert messages == [("whisper:tiny", "Couldn't remove Whisper tiny. model.bin is open in another app.")]


def test_row_view_without_a_catalog_size_waits_for_the_download_total():
    asset = {"id": "voices:x", "label": "x", "downloaded": False}
    live = assets_ctrl._Live(assets_ctrl.STATE_DOWNLOADING, done=0, total=0)
    assert row_view(asset, live)["progressText"] == "Starting"
    live.done, live.total = 50, 200
    view = row_view(asset, live)
    assert (view["progressText"], view["sizeText"], view["name"]) == ("25%", "", "x")


def test_row_roles_are_exposed_by_name():
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    model = AssetRowModel()
    model.set_rows([row_view(_CATALOG[0], None)])
    assert model.data(model.index(0), Qt.ItemDataRole.DisplayRole) == "tiny"
    assert _role(model, 0, "assetId") == "whisper:tiny"
    assert model.count == 1
