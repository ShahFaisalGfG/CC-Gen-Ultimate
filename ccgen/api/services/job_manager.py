# job_manager.py - in-memory job registry; runs Task.prepare()/run() off the event loop
#
# Each UI tab submits its own jobs, but they run one at a time: two speech models or a Whisper
# model and a voice-cloning model competing for the same GPU would both run slower and could run
# out of memory. Waiting jobs report that they are waiting and can be cancelled before they start.
#
# Callbacks execute on a worker thread (via run_in_executor), so events are handed back to the
# loop thread with call_soon_threadsafe before being placed on the per-job asyncio.Queue.
# Cancellation is cooperative: cancel_job() flags the task, which stops at its next segment or
# download chunk and reports a cancelled result.

import asyncio
import logging
import uuid
from collections import OrderedDict
from typing import Any, AsyncIterator, Optional

from ccgen.core import AnySegment
from ccgen.core.tasks import Task, TaskResult, cancelled_result, create_task, failed_result
from ccgen.core.tasks.configs import TaskConfigBase
from ccgen.engines import model_cache

_log = logging.getLogger(__name__)

# Finished results are kept for polling clients, but only the most recent ones, so a long
# session processing thousands of files doesn't grow memory without bound.
_MAX_KEPT_RESULTS = 100


class JobManager:
    """Tracks task jobs, runs them one at a time, and fans out progress events to subscribers."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """(Re)initialize state for the current event loop.

        Called at API startup: this manager is a module-level singleton, but its asyncio
        primitives bind to whichever event loop first uses them, so each app lifecycle (a real
        run, or each test's own TestClient) needs fresh ones.
        """
        self._tasks: dict[str, Task] = {}
        # Set to wake a job still waiting for the run slot when it is cancelled.
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queues: dict[str, "asyncio.Queue[dict[str, Any]]"] = {}
        self._results: "OrderedDict[str, TaskResult]" = OrderedDict()
        self._run_lock = asyncio.Lock()

    async def start_job(self, config: TaskConfigBase) -> str:
        """Create a job id, schedule its task, and return the id.

        Must be called from a coroutine running on the event loop (an async route handler),
        since it schedules the job via asyncio.create_task().
        """
        task = create_task(config)
        self._loop = asyncio.get_running_loop()
        job_id = uuid.uuid4().hex
        queue: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue()
        self._queues[job_id] = queue
        self._tasks[job_id] = task
        self._cancel_events[job_id] = asyncio.Event()
        asyncio.create_task(self._run_job(job_id, task, queue))
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a job. Returns False when the job is unknown."""
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()
            event = self._cancel_events.get(job_id)
            if event is not None and self._loop is not None:
                # Route handlers run on worker threads; asyncio events are set on the loop.
                self._loop.call_soon_threadsafe(event.set)
            return True
        return job_id in self._results

    def cancel_all(self) -> None:
        """Cancel every running or waiting job (used when the app closes)."""
        for job_id in list(self._tasks):
            self.cancel_job(job_id)

    def get_result(self, job_id: str) -> Optional[TaskResult]:
        """Return the completed result for a job, or None while it is still running or waiting."""
        return self._results.get(job_id)

    def is_known(self, job_id: str) -> bool:
        """Return True when the job id was issued by this manager."""
        return job_id in self._tasks or job_id in self._results

    def release_models(self) -> bool:
        """Free every cached model unless a job is running or waiting. Returns True when released."""
        if self._tasks:
            return False
        model_cache.release_all()
        return True

    async def stream(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield queued event dicts for a job until its "finished" event arrives."""
        queue = self._queues.get(job_id)
        if queue is None:
            return
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("event") == "finished":
                    break
        finally:
            if job_id in self._results:
                self._queues.pop(job_id, None)

    async def _run_job(self, job_id: str, task: Task, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        """Wait for the run slot, then run task.prepare()+run() in a worker thread."""
        loop = asyncio.get_running_loop()

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def status_cb(message: str) -> None:
            emit({
                "event": "status", "message": message,
                "stage": task.stage, "step": task.step, "steps": len(task.stages),
            })

        def segment_cb(seg: AnySegment) -> None:
            emit(segment_event(seg, task.stage, task.step))

        def progress_cb(done: int, total: int) -> None:
            emit({
                "event": "progress", "done": done, "total": total,
                "stage": task.stage, "step": task.step, "steps": len(task.stages),
            })

        result: Optional[TaskResult] = None
        try:
            if self._run_lock.locked():
                status_cb("Waiting for another task to finish...")
            if not await self._acquire_run_slot(self._cancel_events[job_id]):
                result = cancelled_result(task.config.input_path)
                return
            try:
                await loop.run_in_executor(None, task.prepare, status_cb, progress_cb)
                if task.cancelled:
                    result = cancelled_result(task.config.input_path)
                else:
                    result = await loop.run_in_executor(None, lambda: task.run(status_cb, segment_cb, progress_cb))
            finally:
                self._run_lock.release()
        except Exception as e:
            if task.cancelled:
                result = cancelled_result(task.config.input_path)
            else:
                _log.error("Job %s failed: %r", job_id, e, exc_info=True)
                result = failed_result(task.config.input_path, e)
        finally:
            result = result or cancelled_result(task.config.input_path)
            self._store_result(job_id, result)
            # Dropping the task releases its engines; models stay in the shared cache.
            self._tasks.pop(job_id, None)
            self._cancel_events.pop(job_id, None)
            emit({
                "event": "finished",
                "success": result.success,
                "error": result.error,
                "error_detail": result.error_detail,
                "error_kind": result.error_kind,
                "cancelled": result.cancelled,
                "output_files": result.output_files,
                "detected_language": result.detected_language,
                "output_languages": result.output_languages,
                "warnings": result.warnings,
            })

    async def _acquire_run_slot(self, cancelled: asyncio.Event) -> bool:
        """Wait for the run slot, giving up as soon as the job is cancelled. True once acquired."""
        if cancelled.is_set():
            return False
        acquire = asyncio.ensure_future(self._run_lock.acquire())
        waiter = asyncio.ensure_future(cancelled.wait())
        try:
            await asyncio.wait({acquire, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
        if not acquire.done():
            # Cancelling a pending acquire leaves the lock free for the next waiter.
            acquire.cancel()
            return False
        if cancelled.is_set():
            self._run_lock.release()
            return False
        return True

    def _store_result(self, job_id: str, result: TaskResult) -> None:
        """Keep a compact copy of the result for polling, evicting the oldest ones."""
        self._results[job_id] = TaskResult(
            success=result.success,
            input_path=result.input_path,
            output_files=result.output_files,
            detected_language=result.detected_language,
            error=result.error,
            error_detail=result.error_detail,
            error_kind=result.error_kind,
            cancelled=result.cancelled,
            warnings=result.warnings,
            output_languages=result.output_languages,
        )
        while len(self._results) > _MAX_KEPT_RESULTS:
            old_id, _ = self._results.popitem(last=False)
            self._queues.pop(old_id, None)


def segment_event(seg: AnySegment, stage: str, step: int) -> dict[str, Any]:
    """Describe one streamed cue for the UI: which text it carries and the stage that made it."""
    if "transliterated" in seg:
        kind, text = "transliteration", seg["transliterated"]  # type: ignore[typeddict-item]
    elif "translated" in seg:
        kind, text = "translation", seg["translated"]  # type: ignore[typeddict-item]
    else:
        kind, text = "transcript", seg.get("text", "")
    return {
        "event": "segment", "kind": kind, "stage": stage, "step": step,
        "id": seg["id"], "start": seg["start"], "end": seg["end"], "text": text,
    }
