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
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from platform_backend.db.models import Claim, Job
from platform_backend.db.session import get_db
from platform_backend.security import (
    current_principal, ensure_can_read, require_reviewer, submitter_id,
)
from platform_backend.services import demo_guard
from platform_backend.services import jobs as job_service
from platform_backend.services.auth import Principal
from platform_backend.services.rate_limit import enforce
from platform_backend.services.claim_service import utc_iso
from platform_backend.services.uploads import read_documents, read_uploads

router = APIRouter(prefix="/api/v1")

# Poll interval for the SSE endpoint. The job row is the progress channel, so this is a
# database read, not a model call.
_STREAM_POLL_SECONDS = 0.4
_STREAM_TIMEOUT_SECONDS = 600
_HEARTBEAT_SECONDS = 15.0


def _job_view(job: Job) -> Dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress or [],
        "claim_id": job.claim_id,
        "error": job.error,
        "created_at": utc_iso(job.created_at),
        "finished_at": utc_iso(job.finished_at),
        "links": {
            "self": f"/api/v1/jobs/{job.id}",
            "stream": f"/api/v1/jobs/{job.id}/stream",
            "claim": f"/api/v1/claims/{job.claim_id}" if job.claim_id else None,
        },
    }


@router.post("/claims", status_code=202)
async def submit_claim(
    request: Request,
    response: Response,
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    user_id: Optional[str] = Form(None),
    files: List[UploadFile] = File([]),
    documents: List[UploadFile] = File([]),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """
    Accept a claim for analysis. Returns 202 immediately; the work happens on a job.

    Images are decoded and persisted here rather than on the worker, so a malformed upload
    fails fast with a 400 the client can act on instead of becoming a job that fails
    asynchronously for a reason the submitter never sees. Caps and content sniffing live in
    `services/uploads`, shared with the unversioned route.
    """
    user_id = submitter_id(principal, user_id)
    if idempotency_key:
        existing = job_service.find_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            # Deliberately 200, not 202: nothing new was accepted.
            return Response(
                content=json.dumps({**_job_view(existing), "idempotent_replay": True}),
                media_type="application/json", status_code=200,
            )

    # The same limits as the dashboard route. This route used to skip the demo capacity
    # guard entirely, which made the per-visitor cap trivially avoidable.
    from platform_backend.api.routes import _submission_checks
    visitor = _submission_checks(request, principal)

    images, image_paths = await read_uploads(files)
    # Accepted here for the same reason images are: a malformed upload should fail
    # fast with a 400 the submitter can act on, not become a job that fails
    # asynchronously. Without this the route accepted `documents` and silently
    # discarded them — an API that drops evidence is worse than one that refuses it.
    doc_parts, document_paths = await read_documents(documents)
    demo_guard.consume(visitor)

    payload = {
        "user_id": user_id, "user_claim": user_claim, "claim_object": claim_object,
        "image_paths": image_paths, "document_paths": document_paths,
    }
    job, created = job_service.create_or_get_job(
        db, user_id=user_id, payload=payload, idempotency_key=idempotency_key,
    )
    if not created:
        # Lost a race with an identical retry: report the job that won, start nothing.
        return Response(
            content=json.dumps({**_job_view(job), "idempotent_replay": True}),
            media_type="application/json", status_code=200,
        )
    job_service.submit(job.id, images, doc_parts)

    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return _job_view(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db),
            principal: Principal = Depends(current_principal)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_can_read(principal, job.user_id, "Job")
    return _job_view(job)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, db: Session = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    """
    Server-sent per-stage progress until the job reaches a terminal state.

    Reads the job row rather than subscribing to a broker. That is not a shortcut: progress
    has to survive a client reconnecting mid-analysis, which means it has to be durable
    anyway, which means the database is already where it belongs.
    """
    owner = db.query(Job).filter(Job.id == job_id).first()
    if owner is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_can_read(principal, owner.user_id, "Job")

    async def events():
        seen: Optional[str] = None
        waited = 0.0
        quiet = 0.0
        while waited < _STREAM_TIMEOUT_SECONDS:
            session = job_service.SessionLocal()
            try:
                job = session.query(Job).filter(Job.id == job_id).first()
                if job is None:
                    return
                snapshot = json.dumps(_job_view(job), sort_keys=True)
                if snapshot != seen:
                    seen = snapshot
                    quiet = 0.0
                    yield f"data: {snapshot}\n\n"
                if job.status in job_service.TERMINAL_STATUSES:
                    return
            finally:
                session.close()
            await asyncio.sleep(_STREAM_POLL_SECONDS)
            waited += _STREAM_POLL_SECONDS
            quiet += _STREAM_POLL_SECONDS

            # The job row does not change for the length of the model call — measured at
            # 12s on free quota and 185s under rate-limit backoff. A proxy that sees no
            # bytes for its idle timeout (~100s on Render) closes the response, and the
            # client watches a job that has in fact completed. An SSE comment is discarded
            # by the browser's parser and keeps the connection provably alive.
            if quiet >= _HEARTBEAT_SECONDS:
                quiet = 0.0
                yield ": keepalive\n\n"

        yield f'data: {json.dumps({"job_id": job_id, "status": "stream_timeout"})}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        # Without this an intermediary buffers the stream and the UI shows nothing until
        # the job finishes, which defeats the whole point of streaming progress.
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, db: Session = Depends(get_db),
              principal: Principal = Depends(current_principal)):
    from platform_backend.api.routes import claim_detail
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    ensure_can_read(principal, claim.user_id)
    return claim_detail(claim)


@router.get("/metrics/llm")
def llm_metrics(days: int = 7, db: Session = Depends(get_db),
                principal: Principal = Depends(require_reviewer)):
    """
    Model usage over the last `days` (1–90): calls per day, p50/p95 latency, list-price cost
    per claim, cache-hit rate, and today's remaining Gemini quota per model.

    Computed from the `llm_calls` table and the quota ledger — nothing here is estimated.
    Reviewer and admin only.
    """
    from platform_backend.services.llm_telemetry import summarise
    return summarise(db, days=days)


class CopilotQuestion(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


@router.post("/copilot/ask")
def copilot_ask(body: CopilotQuestion, request: Request,
                principal: Principal = Depends(require_reviewer)):
    """
    Answer a question about the policy, citing the clauses the answer rests on.

    Retrieval reads only the policy wording. When no clause is close enough the answer is
    "not in the policy" and no model is called. Every citation in the response is a clause
    that was actually retrieved, returned with its text so the reviewer can read it.
    """
    from agent_core.copilot import ask

    # Each question can spend a free-tier model call; one account must not be able to spend
    # the day's budget for everyone.
    enforce(f"copilot:{principal.user_id}", "copilot_questions_per_hour", 3600, "copilot questions")
    bundle = getattr(request.app.state, "index", None)
    if bundle is None or not bundle.policy_clauses():
        raise HTTPException(status_code=503, detail=(
            "The policy index is not built. Run `python -m agent_core.tools.build_index`."))
    try:
        return ask(body.question, bundle).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/claims/{claim_id}/explanation")
def claim_explanation(claim_id: int, db: Session = Depends(get_db),
                      principal: Principal = Depends(current_principal)):
    """
    The rule that decided this claim, and the policy clauses behind it. Deterministic: read
    from the claim's own audit trail and `knowledge/policies/rule_clause_map.yaml`, with no
    model call.
    """
    from agent_core.explanation import explain

    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    # A claimant may read the explanation of their own claim: the policy promises a
    # right to an explanation (REV-2), and that right is the claimant's.
    ensure_can_read(principal, claim.user_id)
    logs = {log.agent_name: (log.outputs or {}) for log in claim.audit_logs}
    return {
        "claim_id": claim.id,
        **explain(
            claim_status=claim.claim_status,
            claim_object=claim.claim_object,
            decision_rule_ids=logs.get("decision", {}).get("rule_ids") or [],
            policy_rule_ids=logs.get("policy_verification", {}).get("rule_ids") or [],
            justification=claim.claim_status_justification or "",
            escalated=bool(claim.manual_review_required),
        ),
    }


@router.get("/claims")
def list_claims(
    after: Optional[int] = None,
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """
    Cursor pagination on the primary key.

    Offset pagination re-scans skipped rows on every page, and silently skips or repeats
    records when rows are inserted while a client is paging. For a review queue that means
    a claim nobody ever sees.
    """
    limit = max(1, min(limit, 200))
    query = db.query(Claim)
    if not principal.is_reviewer:
        query = query.filter(Claim.user_id == principal.username)
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
