"""
Versioned API: the asynchronous claim-submission contract.

`POST /api/v1/claims` returns **202 Accepted** with a job id instead of blocking for the
length of a model call. The result is collected by polling `GET /api/v1/jobs/{id}` or by
subscribing to `GET /api/v1/jobs/{id}/stream`.

The unversioned routes in `routes.py` still work and still block; they are what the current
frontend calls. They are not deleted here because breaking a working UI to land a contract
change is not an improvement — see docs/PHASE_5.1_REPORT.md for the migration path.

**Cursor pagination, not offset.** `GET /api/v1/claims?after=` pages on the primary key.
Offset pagination re-scans the skipped rows on every page and, worse, silently skips or
repeats records when rows are inserted while a client is paging — which for a claims queue
means a claim nobody ever sees.
"""
from __future__ import annotations

import asyncio
import datetime
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy.orm import Session

from platform_backend.db.models import Claim, Job
from platform_backend.db.session import get_db
from platform_backend.services import jobs as job_service

router = APIRouter(prefix="/api/v1")

# Poll interval for the SSE endpoint. The job row is the progress channel, so this is a
# database read, not a model call.
_STREAM_POLL_SECONDS = 0.4
_STREAM_TIMEOUT_SECONDS = 300


def _job_view(job: Job) -> Dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress or [],
        "claim_id": job.claim_id,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "links": {
            "self": f"/api/v1/jobs/{job.id}",
            "stream": f"/api/v1/jobs/{job.id}/stream",
            "claim": f"/api/v1/claims/{job.claim_id}" if job.claim_id else None,
        },
    }


@router.post("/claims", status_code=202)
async def submit_claim(
    response: Response,
    user_id: str = Form(...),
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    files: List[UploadFile] = File([]),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """
    Accept a claim for analysis. Returns 202 immediately; the work happens on a job.

    Images are decoded here rather than on the worker so a malformed upload fails fast with
    a 400 the client can act on, instead of becoming a job that fails asynchronously for a
    reason the submitter never sees.
    """
    if idempotency_key:
        existing = job_service.find_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            # Deliberately 200, not 202: nothing new was accepted.
            return Response(
                content=json.dumps({**_job_view(existing), "idempotent_replay": True}),
                media_type="application/json", status_code=200,
            )

    images: List[Image.Image] = []
    names: List[str] = []
    for upload in files:
        if not upload.filename:
            continue
        raw = await upload.read()
        try:
            probe = Image.open(io.BytesIO(raw))
            probe.verify()                      # verify() leaves the object unusable
            images.append(Image.open(io.BytesIO(raw)))
            names.append(upload.filename)
        except Exception:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail=f"'{upload.filename}' is not a readable image.",
            )

    payload = {
        "user_id": user_id, "user_claim": user_claim, "claim_object": claim_object,
        "image_paths": ";".join(f"uploads/{n}" for n in names) if names else "none",
    }
    job = job_service.create_job(
        db, user_id=user_id, payload=payload, idempotency_key=idempotency_key,
    )
    job_service.submit(job.id, images)

    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return _job_view(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_view(job)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, db: Session = Depends(get_db)):
    """
    Server-sent per-stage progress until the job reaches a terminal state.

    Reads the job row rather than subscribing to a broker. That is not a shortcut: progress
    has to survive a client reconnecting mid-analysis, which means it has to be durable
    anyway, which means the database is already where it belongs.
    """
    if db.query(Job).filter(Job.id == job_id).first() is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def events():
        seen: Optional[str] = None
        waited = 0.0
        while waited < _STREAM_TIMEOUT_SECONDS:
            session = job_service.SessionLocal()
            try:
                job = session.query(Job).filter(Job.id == job_id).first()
                if job is None:
                    return
                snapshot = json.dumps(_job_view(job), sort_keys=True)
                if snapshot != seen:
                    seen = snapshot
                    yield f"data: {snapshot}\n\n"
                if job.status in job_service.TERMINAL_STATUSES:
                    return
            finally:
                session.close()
            await asyncio.sleep(_STREAM_POLL_SECONDS)
            waited += _STREAM_POLL_SECONDS

        yield f'data: {json.dumps({"job_id": job_id, "status": "stream_timeout"})}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        # Without this an intermediary buffers the stream and the UI shows nothing until
        # the job finishes, which defeats the whole point of streaming progress.
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("/claims")
def list_claims(
    after: Optional[int] = None,
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Cursor pagination on the primary key.

    Offset pagination re-scans skipped rows on every page, and silently skips or repeats
    records when rows are inserted while a client is paging. For a review queue that means
    a claim nobody ever sees.
    """
    limit = max(1, min(limit, 200))
    query = db.query(Claim)
    if status:
        query = query.filter(Claim.claim_status == status)
    if after is not None:
        query = query.filter(Claim.id < after)

    rows = query.order_by(Claim.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": rows,
        "next_cursor": rows[-1].id if rows and has_more else None,
        "has_more": has_more,
    }
