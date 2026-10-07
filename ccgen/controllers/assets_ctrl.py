# assets_ctrl.py - Manage Models controller (HTTP/WebSocket client of the embedded API)

from typing import Any, Optional

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWebSockets import QWebSocket

from ccgen.config import profiles
from ccgen.config.capabilities import neural_model_key, translation_asset_ids
from ccgen.config.voices import ENGINE_KOKORO, ENGINE_OMNIVOICE, ENGINE_PIPER, ENGINE_XTTS
from ccgen.controllers.api_client import ApiClient


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
    removeFailed    = Signal(str, str)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self._api = ApiClient(base_url, self)
        self._assets: list[dict[str, Any]] = []
        self._readiness: dict[str, bool] = {}
        self._socket: Optional[QWebSocket] = self._api.open_stream("/assets/stream", self._on_stream_event)
        self.refreshAssets()

    @Property("QVariantList", notify=assetsChanged)  # type: ignore[arg-type]
    def assets(self) -> list:
        """Current catalog snapshot: id/category/label/downloaded/size for every asset."""
        return self._assets

    @Property("QVariantMap", notify=assetsChanged)  # type: ignore[arg-type]
    def readiness(self) -> dict:
        """Map of asset id to whether it is downloaded, for ready/needs-download badges."""
        return self._readiness

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
        """Queue an asset for download."""
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
                self.removeFailed.emit(asset_id, error)
            self.refreshAssets()

        self._api.delete(f"/assets/{asset_id}", done)

    def close(self) -> None:
        """Close the event stream (used on shutdown)."""
        socket, self._socket = self._socket, None
        if socket is not None:
            socket.close()

    def _on_assets(self, data: Any, error: str) -> None:
        """Apply the fetched catalog and notify QML."""
        if error or not isinstance(data, list):
            return
        self._assets = data
        self._readiness = {str(a.get("id")): bool(a.get("downloaded")) for a in data}
        self.assetsChanged.emit()

    def _on_stream_event(self, event: dict[str, Any]) -> None:
        """Re-emit one assets stream event as the matching Qt signal."""
        kind = event.get("event")
        asset_id = str(event.get("id", ""))
        if kind == "queued":
            self.assetQueued.emit(asset_id)
        elif kind == "status":
            self.assetStatus.emit(asset_id, str(event.get("message", "")))
        elif kind == "progress":
            self.assetProgress.emit(asset_id, int(event["done"]), int(event["total"]))
        elif kind == "finished":
            self.assetFinished.emit(asset_id, bool(event.get("success")), str(event.get("error") or ""))
            self.refreshAssets()
