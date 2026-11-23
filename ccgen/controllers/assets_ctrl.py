# assets_ctrl.py - Manage Models controller (HTTP/WebSocket client of the embedded API) and the
# list models its window shows
#
# Each category tab lists groups of models (AssetGroupModel), and each group lists its models
# (AssetRowModel). A download's progress changes one row through dataChanged, never a reset, so
# the window keeps its keyboard focus and a screen reader keeps its place while models download.

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWebSockets import QWebSocket

from ccgen.config import profiles
from ccgen.config.capabilities import neural_model_key, translation_asset_ids
from ccgen.config.voices import ENGINE_KOKORO, ENGINE_OMNIVOICE, ENGINE_PIPER, ENGINE_XTTS
from ccgen.controllers.api_client import ApiClient
from ccgen.core.errors import format_size

_UserRole = Qt.ItemDataRole.UserRole

# A row's download state.
STATE_IDLE = "idle"
STATE_QUEUED = "queued"
STATE_DOWNLOADING = "downloading"
STATE_FAILED = "failed"

# The error the assets stream sends when Cancel stopped a download (asset_manager.CANCELLED).
_CANCELLED = "Cancelled"
# Download speed is measured over at least this many seconds, then smoothed.
_SPEED_WINDOW_S = 1.0


@dataclass
class _Live:
    """What the assets stream has said about one download so far."""

    state: str
    done: int = 0
    total: int = 0
    speed: float = 0.0  # bytes per second, smoothed
    mark_time: float = 0.0
    mark_done: int = 0
    error: str = ""


def _speed_text(bytes_per_second: float) -> str:
    """A download speed in MB/s, e.g. "3.1 MB/s"."""
    return f"{bytes_per_second / 1_000_000:.1f} MB/s"


def row_view(asset: dict[str, Any], live: Optional[_Live]) -> dict[str, Any]:
    """The values one Manage Models row shows, from its catalog entry and its live download state."""
    downloaded = bool(asset.get("downloaded"))
    approx = int(asset.get("approx_size_mb") or 0) * 1_000_000
    size = int(asset.get("size_bytes") or 0)
    state = live.state if live is not None else STATE_IDLE
    if downloaded and state == STATE_FAILED:
        state = STATE_IDLE  # downloaded since (by a task), so the failure no longer matters
    if downloaded and size:
        size_text = format_size(size)
    else:
        size_text = f"about {format_size(approx)}" if approx else ""
    fraction, indeterminate, progress_text = 0.0, False, ""
    if state == STATE_QUEUED:
        indeterminate, progress_text = True, "Queued"
    elif state == STATE_DOWNLOADING and live is not None:
        # The catalog's size is a steady denominator: a multi-file download's own total grows
        # as each file starts, which would make the percentage jump back.
        total = max(approx, live.total)
        if live.done <= 0 or total <= 0:
            indeterminate, progress_text = True, "Starting"
        elif live.done >= total:
            # The bytes are in; converting or unpacking the model can take a while longer.
            fraction, indeterminate, progress_text = 1.0, True, "Finishing"
        else:
            fraction = live.done / total
            progress_text = f"{int(fraction * 100)}%"
            if live.speed > 0:
                progress_text += f" · {_speed_text(live.speed)}"
    return {
        "assetId": str(asset.get("id", "")),
        "label": str(asset.get("label", "")),
        "name": str(asset.get("name") or asset.get("label") or asset.get("id", "")),
        "downloaded": downloaded,
        "downloadState": state,
        "sizeText": size_text,
        "fraction": round(fraction, 3),
        "indeterminate": indeterminate,
        "progressText": progress_text,
        "error": live.error if live is not None and state == STATE_FAILED else "",
    }


class AssetRowModel(QAbstractListModel):
    """The models of one Manage Models group, one row each; see row_view() for the roles."""

    ROLES = ("assetId", "label", "name", "downloaded", "downloadState", "sizeText", "fraction",
             "indeterminate", "progressText", "error")

    countChanged = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._index: dict[str, int] = {}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._rows[index.row()]["label"]
        position = role - _UserRole - 1
        if 0 <= position < len(self.ROLES):
            return self._rows[index.row()][self.ROLES[position]]
        return None

    def roleNames(self) -> dict:
        return {_UserRole + 1 + i: name.encode() for i, name in enumerate(self.ROLES)}

    @Property(int, notify=countChanged)  # type: ignore[arg-type]
    def count(self) -> int:
        """Number of models in the group."""
        return len(self._rows)

    def views(self) -> list[dict[str, Any]]:
        """Every row's values, in order."""
        return list(self._rows)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Show `rows`: the same models in the same order update in place; any other list resets."""
        if [r["assetId"] for r in rows] == [r["assetId"] for r in self._rows]:
            for row in rows:
                self.update_row(row)
            return
        self.beginResetModel()
        self._rows = [dict(r) for r in rows]
        self._index = {r["assetId"]: i for i, r in enumerate(self._rows)}
        self.endResetModel()
        self.countChanged.emit()

    def update_row(self, view: dict[str, Any]) -> bool:
        """Update one row's changed roles; False when the model isn't in this group."""
        position = self._index.get(view["assetId"])
        if position is None:
            return False
        current = self._rows[position]
        changed = [_UserRole + 1 + i for i, name in enumerate(self.ROLES) if current.get(name) != view.get(name)]
        if changed:
            current.update(view)
            index = self.index(position)
            self.dataChanged.emit(index, index, changed)
        return True


def _group_summary(views: list[dict[str, Any]]) -> dict[str, Any]:
    """A group's counts and the models its "Download all" and "Remove all" buttons act on."""
    return {
        "total": len(views),
        "downloadedCount": sum(1 for v in views if v["downloaded"]),
        "downloadIds": [v["assetId"] for v in views
                        if not v["downloaded"] and v["downloadState"] in (STATE_IDLE, STATE_FAILED)],
        "removeIds": [v["assetId"] for v in views if v["downloaded"] and v["downloadState"] == STATE_IDLE],
    }


class AssetGroupModel(QAbstractListModel):
    """The groups of one Manage Models tab. Roles: engine (the group's name), rows (its
    AssetRowModel), total, downloadedCount, downloadIds, and removeIds."""

    ROLES = ("engine", "rows", "total", "downloadedCount", "downloadIds", "removeIds")

    countChanged = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._groups: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._groups)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._groups):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._groups[index.row()]["engine"]
        position = role - _UserRole - 1
        if 0 <= position < len(self.ROLES):
            return self._groups[index.row()][self.ROLES[position]]
        return None

    def roleNames(self) -> dict:
        return {_UserRole + 1 + i: name.encode() for i, name in enumerate(self.ROLES)}

    @Property(int, notify=countChanged)  # type: ignore[arg-type]
    def count(self) -> int:
        """Number of groups in the tab."""
        return len(self._groups)

    def rows(self, engine: str) -> Optional[AssetRowModel]:
        """The row model of one group, None when the tab has no such group."""
        group = next((g for g in self._groups if g["engine"] == engine), None)
        return group["rows"] if group else None

    def set_groups(self, groups: list[tuple[str, list[dict[str, Any]]]]) -> None:
        """Show (group name, row views) pairs: the same groups update in place; others reset."""
        if [name for name, _ in groups] == [g["engine"] for g in self._groups]:
            for position, (_, views) in enumerate(groups):
                self._groups[position]["rows"].set_rows(views)
                self._refresh(position)
            return
        self.beginResetModel()
        old = self._groups
        self._groups = []
        for name, views in groups:
            rows = AssetRowModel(self)
            rows.set_rows(views)
            self._groups.append({"engine": name, "rows": rows, **_group_summary(views)})
        self.endResetModel()
        for group in old:
            group["rows"].deleteLater()
        self.countChanged.emit()

    def update_row(self, engine: str, view: dict[str, Any]) -> None:
        """Update one model's row and its group's counts."""
        for position, group in enumerate(self._groups):
            if group["engine"] == engine and group["rows"].update_row(view):
                self._refresh(position)
                return

    def _refresh(self, position: int) -> None:
        """Recount one group, telling QML only when something changed."""
        group = self._groups[position]
        summary = _group_summary(group["rows"].views())
        changed = [_UserRole + 1 + self.ROLES.index(key) for key, value in summary.items() if group[key] != value]
        if changed:
            group.update(summary)
            index = self.index(position)
            self.dataChanged.emit(index, index, changed)


class AssetsController(QObject):
    """Lists and manages downloadable models/engines/languages via the embedded API."""

    assetsChanged   = Signal()
    assetQueued     = Signal(str)
    # 64-bit: byte counts for multi-gigabyte models (e.g. large-v3, ~3.1 GB) overflow a
    # plain 32-bit Qt `int` (max ~2.147 GB), which raised inside PySide6's binding layer
    # and silently dropped every progress event for any asset past that size.
    assetProgress   = Signal(str, 'qlonglong', 'qlonglong')  # type: ignore[arg-type]
    assetStatus     = Signal(str, str)
    assetFinished   = Signal(str, bool, str)
    # (asset id, a plain message naming the model, for the window's banner)
    removeFailed    = Signal(str, str)
    busyChanged     = Signal(bool)
    busyTextChanged = Signal()

    def __init__(self, base_url: str, parent=None, clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self._api = ApiClient(base_url, self)
        self._clock = clock
        self._assets: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._readiness: dict[str, bool] = {}
        self._live: dict[str, _Live] = {}  # downloads queued, running, or failed
        self._groups: dict[str, AssetGroupModel] = {}
        self._busy = False
        self._busy_text = ""
        self._socket: Optional[QWebSocket] = self._api.open_stream("/assets/stream", self._on_stream_event)
        self.refreshAssets()

    @Property("QVariantList", notify=assetsChanged)  # type: ignore[arg-type]
    def assets(self) -> list:
        """Current catalog snapshot: id/category/engine/label/name/downloaded/size for every asset."""
        return self._assets

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        """True while a download is queued or running; installing an update waits for it."""
        return self._busy

    @Property(str, notify=busyTextChanged)  # type: ignore[arg-type]
    def busyText(self) -> str:
        """What the downloads are doing, for the main window, e.g. "Downloading Whisper small, 42%"
        ("" while nothing downloads)."""
        return self._busy_text

    @Property("QVariantMap", notify=assetsChanged)  # type: ignore[arg-type]
    def readiness(self) -> dict:
        """Map of asset id to whether it is downloaded, for ready/needs-download badges."""
        return self._readiness

    @Property(float, notify=assetsChanged)  # type: ignore[arg-type]
    def usedBytes(self) -> float:
        """Disk space the downloaded models take, in bytes."""
        return float(self._used_bytes())

    @Property(str, notify=assetsChanged)  # type: ignore[arg-type]
    def usedText(self) -> str:
        """Disk space the downloaded models take, e.g. "3.4 GB"."""
        return format_size(self._used_bytes())

    @Property(list, notify=assetsChanged)  # type: ignore[arg-type]
    def downloadedIds(self) -> list:
        """Ids of every downloaded model, for "Free up space"."""
        return [str(a.get("id")) for a in self._assets if a.get("downloaded")]

    @Slot(str, result=QObject)
    def groups(self, category: str) -> QObject:
        """The groups of one Manage Models tab ("whisper", "translation", "transliteration", "voices"),
        an AssetGroupModel kept up to date as the catalog loads and models download."""
        if category not in self._groups:
            self._groups[category] = AssetGroupModel(self)
            self._apply_catalog()
        return self._groups[category]

    @Slot(str, str, result=str)
    def whisperAssetId(self, model_name: str, profile: str) -> str:
        """Catalog id of a Whisper model ("auto" resolves with the performance profile)."""
        return f"whisper:{profiles.whisper_model(model_name, profile)}"

    @Slot(str, str, str, str, result=list)
    def translationAssetIds(self, source: str, target: str, engine: str, profile: str) -> list:
        """Catalog ids of every model `engine` needs to translate source→target ("auto": not known yet)."""
        known = "" if source == "auto" else source
        ids: list[str] = []
        for resolved in sorted(profiles.translation_engines(engine, profile, source, target)):
            ids += [i for i in translation_asset_ids(known, target, resolved) if i not in ids]
        return ids

    @Slot(str, str, str, result=str)
    def voiceAssetId(self, mode: str, voice_key: str, profile: str) -> str:
        """Catalog id of what a dubbing mode downloads: its model, or a Piper voice ("" when unknown)."""
        mode = profiles.dub_engine(mode, profile).mode
        if mode == ENGINE_PIPER:
            return f"voices:{voice_key}" if voice_key.startswith(f"{ENGINE_PIPER}:") else ""
        return f"voices:{mode}" if mode in (ENGINE_OMNIVOICE, ENGINE_XTTS, ENGINE_KOKORO) else ""

    @Slot(str, str, result=str)
    def neuralAssetId(self, source: str, target: str) -> str:
        """Catalog id of the neural transliteration model for a script pair, "" when none exists."""
        key = neural_model_key(source, target)
        return f"transliteration:{key}" if key else ""

    @Slot()
    def refreshAssets(self) -> None:
        """Re-fetch the asset catalog from the embedded API."""
        self._api.get("/assets", self._on_assets)

    @Slot(str)
    def downloadAsset(self, asset_id: str) -> None:
        """Queue an asset for download (also "Try again" after a failure)."""
        self._api.post(f"/assets/{asset_id}/download")

    @Slot(str)
    def cancelAsset(self, asset_id: str) -> None:
        """Cancel a queued or in-progress asset download."""
        self._api.post(f"/assets/{asset_id}/cancel")

    @Slot(str)
    def removeAsset(self, asset_id: str) -> None:
        """Delete a downloaded asset from local storage, reporting failures to QML."""

        def done(_data: Any, error: str) -> None:
            if error:
                self.removeFailed.emit(asset_id, f"Couldn't remove {self._name(asset_id)}. {error}")
            self.refreshAssets()

        self._api.delete(f"/assets/{asset_id}", done)

    def close(self) -> None:
        """Close the event stream (used on shutdown)."""
        socket, self._socket = self._socket, None
        if socket is not None:
            socket.close()

    # ── Catalog ──────────────────────────────────────────────────────────────

    def _on_assets(self, data: Any, error: str) -> None:
        """Apply the fetched catalog and notify QML."""
        if error or not isinstance(data, list):
            return
        self._assets = data
        self._by_id = {str(a.get("id")): a for a in data}
        self._readiness = {asset_id: bool(a.get("downloaded")) for asset_id, a in self._by_id.items()}
        # A failure is forgotten once the model is there after all (a task downloaded it).
        for asset_id in [i for i, live in self._live.items() if live.state == STATE_FAILED]:
            if self._readiness.get(asset_id):
                del self._live[asset_id]
        self._apply_catalog()
        self.assetsChanged.emit()
        self._update_busy()

    def _apply_catalog(self) -> None:
        """Lay the catalog out in each tab's groups, updating rows in place where they already show."""
        layout: dict[str, dict[str, list[dict[str, Any]]]] = {category: {} for category in self._groups}
        for asset in self._assets:
            category = str(asset.get("category"))
            if category in layout:
                layout[category].setdefault(str(asset.get("engine")), []).append(self._view(asset))
        for category, groups in layout.items():
            self._groups[category].set_groups(list(groups.items()))

    def _view(self, asset: dict[str, Any]) -> dict[str, Any]:
        """One asset's row values."""
        return row_view(asset, self._live.get(str(asset.get("id"))))

    def _refresh_row(self, asset_id: str) -> None:
        """Show one model's changed state in its row."""
        asset = self._by_id.get(asset_id)
        model = self._groups.get(str(asset.get("category"))) if asset else None
        if asset is not None and model is not None:
            model.update_row(str(asset.get("engine")), self._view(asset))

    def _used_bytes(self) -> int:
        """Bytes the downloaded models take on disk."""
        return sum(int(a.get("size_bytes") or 0) for a in self._assets if a.get("downloaded"))

    def _name(self, asset_id: str) -> str:
        """The model in a sentence ("Whisper small"), its id until the catalog has loaded."""
        asset = self._by_id.get(asset_id)
        return str(asset.get("name") or asset.get("label") or asset_id) if asset else asset_id

    # ── Download events ──────────────────────────────────────────────────────

    def _on_stream_event(self, event: dict[str, Any]) -> None:
        """Apply one assets stream event to its row and re-emit it as the matching Qt signal."""
        kind = event.get("event")
        asset_id = str(event.get("id", ""))
        if kind == "queued":
            self._live[asset_id] = _Live(STATE_QUEUED)
            self._changed(asset_id)
            self.assetQueued.emit(asset_id)
        elif kind == "status":
            self._start(asset_id)
            self._changed(asset_id)
            self.assetStatus.emit(asset_id, str(event.get("message", "")))
        elif kind == "progress":
            done, total = int(event["done"]), int(event["total"])
            self._measure(self._start(asset_id), done, total)
            self._changed(asset_id)
            self.assetProgress.emit(asset_id, done, total)
        elif kind == "finished":
            success, error = bool(event.get("success")), str(event.get("error") or "")
            self._live.pop(asset_id, None)
            if success and asset_id in self._by_id:
                # Shown as downloaded at once; the refresh below brings its size on disk.
                self._by_id[asset_id]["downloaded"] = True
            elif not success and error != _CANCELLED:
                self._live[asset_id] = _Live(STATE_FAILED, error=error or "The download stopped. Try again.")
            self._changed(asset_id)
            self.assetFinished.emit(asset_id, success, error)
            self.refreshAssets()

    def _start(self, asset_id: str) -> _Live:
        """The download's live state, marked as running (the worker has reached it)."""
        live = self._live.get(asset_id)
        if live is None or live.state != STATE_DOWNLOADING:
            done = live.done if live is not None else 0
            live = self._live[asset_id] = _Live(STATE_DOWNLOADING, done=done, mark_time=self._clock(), mark_done=done)
        return live

    def _measure(self, live: _Live, done: int, total: int) -> None:
        """Record progress and update the download speed, averaged over at least a second."""
        now = self._clock()
        if done < live.mark_done:
            live.mark_time, live.mark_done = now, done  # a new file started from zero
        elif now - live.mark_time >= _SPEED_WINDOW_S:
            rate = (done - live.mark_done) / (now - live.mark_time)
            live.speed = rate if live.speed <= 0 else (live.speed + rate) / 2
            live.mark_time, live.mark_done = now, done
        live.done, live.total = done, total

    def _changed(self, asset_id: str) -> None:
        """Update the row, the busy flag, and the main window's text after a download event."""
        self._refresh_row(asset_id)
        self._update_busy()

    def _update_busy(self) -> None:
        """busyChanged fires when the first download is queued and the last ends; busyText follows."""
        busy = any(live.state in (STATE_QUEUED, STATE_DOWNLOADING) for live in self._live.values())
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit(busy)
        text = self._describe_busy()
        if text != self._busy_text:
            self._busy_text = text
            self.busyTextChanged.emit()

    def _describe_busy(self) -> str:
        """The busy text: "Downloading Whisper small, 42% (2 more waiting)", "Waiting to download
        3 models", or "" while nothing downloads."""
        running = [i for i, live in self._live.items() if live.state == STATE_DOWNLOADING]
        waiting = [i for i, live in self._live.items() if live.state == STATE_QUEUED]
        if running:
            asset_id = running[0]
            text = f"Downloading {self._name(asset_id)}"
            asset = self._by_id.get(asset_id, {"id": asset_id})
            view = row_view(asset, self._live[asset_id])
            if not view["indeterminate"]:
                text += f", {int(view['fraction'] * 100)}%"
            others = len(running) - 1 + len(waiting)
            return text + (f" ({others} more waiting)" if others else "")
        if len(waiting) == 1:
            return f"Waiting to download {self._name(waiting[0])}"
        if waiting:
            return f"Waiting to download {len(waiting)} models"
        return ""
