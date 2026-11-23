# assets.py - routes to list, download, cancel, and remove Manage Models catalog assets

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ccgen.api.schemas.assets import AssetOut
from ccgen.api.services.asset_manager import AssetManager

_log = logging.getLogger(__name__)
router = APIRouter()
_manager = AssetManager()


def reset_manager() -> None:
    """Reinitialize the asset manager's queue state for a fresh app lifecycle."""
    _manager.reset()


@router.get("/assets")
def list_assets() -> list[AssetOut]:
    """Return the current catalog of downloadable models/engines/languages."""
    return [AssetOut(**asset) for asset in _manager.list_assets()]


@router.post("/assets/{asset_id}/download")
async def download_asset(asset_id: str) -> dict[str, bool]:
    """Queue an asset for download."""
    await _manager.enqueue_download(asset_id)
    return {"queued": True}


@router.post("/assets/{asset_id}/cancel")
async def cancel_asset(asset_id: str) -> dict[str, bool]:
    """Cancel a queued or in-progress asset download (on the event loop, which owns the stream)."""
    return {"cancelled": _manager.cancel(asset_id)}


@router.delete("/assets/{asset_id}")
def remove_asset(asset_id: str) -> dict[str, bool]:
    """Delete a downloaded asset from local storage; a failure's detail is one plain sentence."""
    try:
        _manager.remove(asset_id)
        return {"removed": True}
    except Exception as e:
        _log.error("Failed to remove asset %s: %r", asset_id, e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.websocket("/assets/stream")
async def stream_assets(websocket: WebSocket) -> None:
    """Stream live queued/status/progress/finished events for all asset downloads."""
    await websocket.accept()
    try:
        async for event in _manager.stream():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        _log.debug("Client disconnected from assets stream")
