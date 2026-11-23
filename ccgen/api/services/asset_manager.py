# asset_manager.py - single-worker download queue for Manage Models assets; runs
# asset_registry's blocking download/delete off the event loop and fans out progress
# events to WebSocket subscribers.
#
# Downloads are FIFO and one at a time (even for "Download All"), to keep bandwidth/CPU
# usage predictable and progress state simple. A download already in flight can also be
# cancelled: none of the underlying libraries expose an abort hook directly, so cancelling
# sets an Event that asset_registry's progress callback checks on the next reported chunk,
# unwinding the blocking call from the inside instead. Failures reach the stream and the
# remove route as one plain sentence (ccgen.core.errors); the original text goes to the log.

import asyncio
import logging
import threading
from typing import Any, AsyncIterator, Callable, Optional

from ccgen.core import errors
from ccgen.utils import asset_registry

_log = logging.getLogger(__name__)

# The "finished" error of a download stopped by Cancel.
CANCELLED = "Cancelled"
# What a failure nothing else explains says, pointing at the log Preferences > Advanced opens. The
# app puts "Couldn't remove <model>." before the removal sentence.
_DOWNLOAD_FAILED = ("The download stopped with an unexpected error. Try again; if it happens again, "
                    "open the logs folder from Preferences > Advanced.")
_REMOVE_FAILED = ("Close any task that uses the model, then try again. If it happens again, open the logs "
                  "folder from Preferences > Advanced.")


def plain_error(error: BaseException, fallback: str) -> str:
    """One plain sentence with a next step for a failed download or removal (`fallback` when unknown)."""
    problem = errors.describe(error)
    return fallback if problem.kind == errors.KIND_UNKNOWN else problem.message


class AssetManager:
    """Queues asset downloads one at a time and streams their progress/status events."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """(Re)initialize all queue/task state for the current event loop.

        Called at API startup: this manager is a module-level singleton, but its
        asyncio.Queues bind to whichever event loop first uses them, so a fresh app
        lifecycle (a real run, or each test's own TestClient) needs fresh queue instances
        rather than ones left bound to a previous, now-dead loop.
        """
        self._download_queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._events: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue()
        self._pending: set[str] = set()
        self._active: Optional[str] = None
        self._active_cancel_event: Optional[threading.Event] = None
        self._worker_task: Optional[asyncio.Task] = None

    async def enqueue_download(self, asset_id: str) -> None:
        """Queue an asset for download; starts the worker loop if it isn't already running."""
        if asset_id in self._pending or asset_id == self._active:
            return
        self._pending.add(asset_id)
        await self._download_queue.put(asset_id)
        await self._events.put({"event": "queued", "id": asset_id})
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run_worker())

    def cancel(self, asset_id: str) -> bool:
        """Cancel a queued or in-progress download. Returns False if the asset isn't tracked.

        Call it on the event loop. A queued download is dropped at once and reported finished
        (cancelled) here, since the worker never reaches it; one in progress reports that itself
        once it unwinds.
        """
        if asset_id in self._pending:
            self._pending.discard(asset_id)
            self._events.put_nowait({"event": "finished", "id": asset_id, "success": False, "error": CANCELLED})
            return True
        if asset_id == self._active and self._active_cancel_event is not None:
            self._active_cancel_event.set()
            return True
        return False

    def remove(self, asset_id: str) -> None:
        """Delete a downloaded asset synchronously; raises RuntimeError with a plain sentence on failure."""
        try:
            asset_registry.delete_asset(asset_id)
        except Exception as e:
            raise RuntimeError(plain_error(e, _REMOVE_FAILED)) from e

    def list_assets(self) -> list[asset_registry.AssetInfo]:
        """Return the current catalog snapshot."""
        return asset_registry.list_assets()

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield queued asset events (queued/status/progress/finished) forever."""
        while True:
            yield await self._events.get()

    async def _run_worker(self) -> None:
        """Drain the download queue one asset at a time."""
        loop = asyncio.get_running_loop()

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(self._events.put_nowait, event)

        while not self._download_queue.empty():
            asset_id = await self._download_queue.get()
            if asset_id not in self._pending:
                continue  # cancelled while queued
            self._pending.discard(asset_id)
            self._active = asset_id
            await self._download_one(asset_id, emit, loop)
            self._active = None
            self._active_cancel_event = None

    async def _download_one(
        self,
        asset_id: str,
        emit: Callable[[dict[str, Any]], None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Run one asset's blocking download in an executor thread, emitting its events."""

        def status_cb(message: str) -> None:
            emit({"event": "status", "id": asset_id, "message": message})

        def progress_num_cb(done: int, total: int) -> None:
            emit({"event": "progress", "id": asset_id, "done": done, "total": total})

        cancel_event = threading.Event()
        self._active_cancel_event = cancel_event
        try:
            await loop.run_in_executor(
                None,
                asset_registry.download_asset,
                asset_id,
                status_cb,
                progress_num_cb,
                cancel_event.is_set,
            )
            emit({"event": "finished", "id": asset_id, "success": True, "error": ""})
        except Exception as e:
            if cancel_event.is_set():
                emit({"event": "finished", "id": asset_id, "success": False, "error": CANCELLED})
            else:
                _log.error("Asset download failed (%s): %r", asset_id, e, exc_info=True)
                emit({"event": "finished", "id": asset_id, "success": False,
                      "error": plain_error(e, _DOWNLOAD_FAILED)})
