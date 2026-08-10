"""
Job execution for claim analysis.

**The problem this solves.** Analysing a claim costs one multimodal request, measured at
~14 seconds end to end. The synchronous route held a worker open for the whole of it, which
means concurrency is bounded by worker count, a slow model becomes a site outage, and a
client timeout throws away work already paid for out of a 20-request daily budget.

**The executor is a bounded thread pool, and that is a deliberate limitation.** The original
brief specified ARQ over Redis, which is the right answer for horizontal scale. This project
runs with no broker and no budget to add one, so pretending otherwise by writing code against
a Redis that is never up would be worse than saying so. What matters is that the *contract*
is right — 202, a durable job row, poll and stream endpoints — because that is the part
clients depend on. Swapping `ThreadPoolExecutor` for an ARQ worker changes this file and
nothing else.

Two consequences of a single-process pool, stated rather than discovered later:

* jobs do not survive a restart — `reap_orphans()` marks them failed at startup rather than
  leaving them `running` forever;
* the pool is the concurrency limit, and it is deliberately small because the real ceiling
  is 5 requests per minute of free-tier quota, not CPU.
"""
from __future__ import annotations

import datetime
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from agent_core.service import PIPELINE_STAGES, ClaimAnalysis, analyse_claim_events
from platform_backend.db.models import Job
from platform_backend.db.session import SessionLocal
from platform_backend.services.claim_service import (
    _analysis_to_db_claim,
    _audit_logs_for,
    _save_claim_and_audit,
)

# Small on purpose: the binding constraint is 5 requests/minute of free quota, not CPU.
# A larger pool would only queue harder against the rate governor.
MAX_CONCURRENT_JOBS = 4

_executor: Optional[ThreadPoolExecutor] = None
_lock = threading.Lock()

TERMINAL_STATUSES = frozenset({"succeeded", "failed"})


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="aurelix-job",
            )
        return _executor


def shutdown(wait: bool = True) -> None:
    """Drain in-flight jobs on shutdown rather than dropping paid-for work."""
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=wait)
            _executor = None


# ─── Job lifecycle ──────────────────────────────────────────────────────────

def find_by_idempotency_key(db: Session, user_id: str, key: str) -> Optional[Job]:
    """
    An Idempotency-Key is scoped per user.

    Without this a client retry — a flaky connection, a double-tapped button — spends a
    second request out of a 20-per-day budget and creates a duplicate claim record. Both
    are worse than returning the original job.
    """
    if not key:
        return None
    return (
        db.query(Job)
        .filter(Job.user_id == user_id, Job.idempotency_key == key)
        .order_by(Job.created_at.desc())
        .first()
    )


def create_job(
    db: Session, *, user_id: str, payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> Job:
    job = Job(
        id=str(uuid.uuid4()), user_id=user_id, status="queued",
        progress=[{"stage": s, "status": "pending"} for s in PIPELINE_STAGES],
        idempotency_key=idempotency_key or None, submitted_payload=payload,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def reap_orphans(db: Session) -> int:
    """
    Fail jobs left `running` by a process that died.

    A single-process pool cannot resume them, and a job stuck in `running` forever is worse
    than one that reports honestly that it was interrupted: a client polls it indefinitely,
    and no operator ever finds out.
    """
    orphans = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
    for job in orphans:
        job.status = "failed"
        job.error = "Interrupted: the worker process stopped before this job completed."
        job.finished_at = _now()
    if orphans:
        db.commit()
    return len(orphans)


# ─── Execution ──────────────────────────────────────────────────────────────

def _record(db: Session, job: Job, stage: str, status: str) -> None:
    # Fresh dicts, not the ones already inside job.progress.
    #
    # A plain JSON column has no mutation tracking: SQLAlchemy decides whether to emit an
    # UPDATE by comparing the attribute's old snapshot to its new value. Mutating the
    # existing dicts in place mutates the snapshot too, so old == new and the write is
    # silently dropped — the job completed correctly and reported no progress at all.
    now = _now().isoformat()
    progress: List[Dict[str, Any]] = [dict(e) for e in (job.progress or [])]
    for entry in progress:
        if entry["stage"] == stage:
            entry["status"] = status
            entry["at"] = now
            break
    else:
        progress.append({"stage": stage, "status": status, "at": now})
    job.progress = progress
    job.stage = stage
    job.updated_at = _now()
    db.commit()


def run_job(job_id: str, images: Optional[list] = None) -> None:
    """
    Execute one job. Runs on a pool thread with its own session — a Session is not
    thread-safe and must never be shared with the request that created the job.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None or job.status in TERMINAL_STATUSES:
            return

        job.status = "running"
        job.started_at = _now()
        db.commit()

        payload = dict(job.submitted_payload or {})
        analysis: Optional[ClaimAnalysis] = None
        for event in analyse_claim_events(
            user_id=payload.get("user_id", ""),
            user_claim=payload.get("user_claim", ""),
            claim_object=payload.get("claim_object", ""),
            image_paths=payload.get("image_paths", ""),
            images=images or None,
            image_base_dir=payload.get("image_base_dir"),
            user_history=payload.get("user_history"),
            evidence_rules=payload.get("evidence_rules"),
        ):
            if event["stage"] == "done":
                analysis = event["analysis"]
            else:
                _record(db, job, event["stage"], event["status"])

        assert analysis is not None
        db_claim = _analysis_to_db_claim(
            analysis, payload.get("user_id", ""), payload.get("image_paths", ""),
            payload.get("user_claim", ""), payload.get("claim_object", ""),
        )
        db_claim = _save_claim_and_audit(db, db_claim, _audit_logs_for(analysis))

        job.claim_id = db_claim.id
        job.status = "succeeded"
        job.finished_at = _now()
        db.commit()

    except Exception as e:  # noqa: BLE001 - a failed job must report, not vanish
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is not None:
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
            job.finished_at = _now()
            db.commit()
    finally:
        db.close()


def submit(job_id: str, images: Optional[list] = None) -> None:
    """Hand the job to the pool. Returns immediately."""
    executor().submit(run_job, job_id, images)
