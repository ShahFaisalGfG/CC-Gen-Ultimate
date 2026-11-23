# jobs.py - routes to validate, start, poll, cancel, and stream task jobs

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, WebSocket, WebSocketDisconnect

from ccgen.api.schemas.job import config_errors, parse_task_config
from ccgen.api.services.job_manager import JobManager

_log = logging.getLogger(__name__)
router = APIRouter()
_manager = JobManager()


def reset_manager() -> None:
    """Rebind the job manager to the current app lifecycle's event loop (called at API startup)."""
    _manager.reset()


def cancel_all_jobs() -> None:
    """Cancel every running or waiting job; the desktop app calls this as it closes."""
    _manager.cancel_all()


@router.post("/jobs")
async def start_job(body: dict[str, Any] = Body(...)) -> dict[str, str]:
    """Start a generate, translate, transliterate, dub, or workflow job."""
    try:
        config = parse_task_config(body)
        job_id = await _manager.start_job(config)
        return {"job_id": job_id}
    except Exception as e:
        _log.error("Failed to start job: %r", e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/jobs/validate")
def validate_job(body: dict[str, Any] = Body(...)) -> dict[str, list[str]]:
    """Return every reason a job body can't run; an empty list means it is ready to start."""
    return {"errors": config_errors(body)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Return the current status/result snapshot for a job."""
    if not _manager.is_known(job_id):
        raise HTTPException(status_code=404, detail="Unknown job id")
    result = _manager.get_result(job_id)
    if result is None:
        return {"job_id": job_id, "busy": True}
    return {
        "job_id": job_id,
        "busy": False,
        "success": result.success,
        "error": result.error,
        "error_detail": result.error_detail,
        "output_files": result.output_files,
        "warnings": result.warnings,
    }


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, bool]:
    """Request cancellation of a running or waiting job."""
    if not _manager.cancel_job(job_id):
        raise HTTPException(status_code=404, detail="Unknown job id")
    return {"cancelled": True}


@router.post("/jobs/release-models")
def release_models() -> dict[str, bool]:
    """Free cached models once the client's queue is done; refused while any job is active."""
    return {"released": _manager.release_models()}


@router.websocket("/jobs/{job_id}/stream")
async def stream_job(websocket: WebSocket, job_id: str) -> None:
    """Stream live segment/progress/status/finished events for a job."""
    await websocket.accept()
    try:
        async for event in _manager.stream(job_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        _log.debug("Client disconnected from job %s stream", job_id)
