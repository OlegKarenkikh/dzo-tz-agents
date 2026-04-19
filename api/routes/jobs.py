import asyncio
import json
import logging
import math
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.schemas import PaginatedResponse
from api.security import require_api_key
from shared.database import (
    count_history as db_count_history,
    delete_job as db_delete_job,
    get_history as db_get_history,
    get_job as db_get_job,
)

logger = logging.getLogger("api")

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=None)
def get_job(job_id: str, _key: str = Depends(require_api_key)):
    job = db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, _key: str = Depends(require_api_key)):
    job = db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    db_delete_job(job_id)
    return {"deleted": True, "job_id": job_id}


@router.get("/history", response_model=PaginatedResponse)
def get_history(
    agent: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _key: str = Depends(require_api_key),
):
    offset = (page - 1) * per_page
    total = db_count_history(agent=agent)
    items = db_get_history(agent=agent, limit=per_page, offset=offset)
    pages = max(1, math.ceil(total / per_page))
    return PaginatedResponse(
        total=total, page=page, per_page=per_page, pages=pages,
        has_next=page < pages, items=items,
    )


@router.get("/stats")
def get_stats(_key: str = Depends(require_api_key)):
    from shared.database import get_stats as db_get_stats
    return db_get_stats()


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """SSE endpoint для отслеживания прогресса задачи в реальном времени."""

    async def _event_gen():
        last_events_count = 0
        poll_interval = 1.0
        max_idle_sec = 300.0
        idle_sec = 0.0
        while True:
            job = db_get_job(job_id)
            if not job:
                yield 'event: error\ndata: {"message":"not_found"}\n\n'
                return
            result = job.get("result") or {}
            log = result.get("processing_log") or {}
            events = log.get("events") or []
            new_events = events[last_events_count:]
            for ev in new_events:
                yield "event: log\ndata: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
            last_events_count = len(events)
            status = job.get("status", "running")
            if status in ("done", "error"):
                payload = {"status": status, "decision": job.get("decision")}
                if status == "error":
                    payload["error"] = job.get("error")
                yield "event: done\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                return
            yield "event: heartbeat\ndata: " + json.dumps(
                {"status": status, "ts": datetime.now(UTC).isoformat()}
            ) + "\n\n"
            await asyncio.sleep(poll_interval)
            idle_sec += poll_interval
            if idle_sec > max_idle_sec:
                yield "event: timeout\ndata: {}\n\n"
                return

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
