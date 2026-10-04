"""
Job lifecycle edge cases from the interview audit.

* **Idempotency under a race.** The key was indexed but not unique, so two retries that both
  passed the lookup created two jobs — two model requests for one claim. A unique index plus
  `create_or_get_job` makes the race lose cleanly.
* **Reaping only `running` jobs.** Failing `queued` jobs at startup threw away work that had
  never begun; it is now restarted from the evidence saved at submission.
* **Run at most once.** A job dispatched twice is claimed atomically, so it runs once.
"""
from __future__ import annotations

import io
import threading
import uuid

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from platform_backend.db.models import Base, Job
from platform_backend.services import jobs
from tests.test_backend_pipeline import GeminiSpy


@pytest.fixture
def Session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    from platform_backend.db import session as session_module
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    yield factory
    jobs.shutdown(wait=True)


PAYLOAD = {"user_id": "u1", "user_claim": "The front bumper is dented.", "claim_object": "car",
           "image_paths": "none", "document_paths": "none"}


# ─── Idempotency ────────────────────────────────────────────────────────────

def test_the_same_key_returns_the_same_job(Session):
    db = Session()
    first, created_first = jobs.create_or_get_job(db, user_id="u1", payload=PAYLOAD, idempotency_key="k1")
    second, created_second = jobs.create_or_get_job(db, user_id="u1", payload=PAYLOAD, idempotency_key="k1")
    db.close()
    assert (created_first, created_second) == (True, False)
    assert first.id == second.id


def test_keys_are_scoped_per_user_and_absent_keys_never_collide(Session):
    db = Session()
    ids = []
    for user, key in (("u1", "k1"), ("u2", "k1"), ("u1", None), ("u1", None)):
        job, created = jobs.create_or_get_job(db, user_id=user, payload=PAYLOAD, idempotency_key=key)
        ids.append(job.id)                       # read while the session is open
        assert created
    db.close()
    assert len(set(ids)) == 4


def test_concurrent_retries_create_exactly_one_job(Session):
    """Eight threads submit the same key at the same instant; one job must exist afterwards."""
    barrier = threading.Barrier(8)
    ids, errors = [], []

    def submit():
        db = Session()
        try:
            barrier.wait()
            job, _ = jobs.create_or_get_job(db, user_id="u1", payload=PAYLOAD, idempotency_key="race")
            ids.append(job.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    db = Session()
    rows = db.query(Job).filter(Job.idempotency_key == "race").count()
    db.close()
    assert not errors
    assert rows == 1
    assert len(set(ids)) == 1


# ─── Reaping and requeueing ─────────────────────────────────────────────────

def _saved_photo() -> str:
    from platform_backend.services.uploads import upload_dir
    arr = np.random.default_rng(0).integers(40, 215, (620, 900, 3), dtype=np.uint8)
    name = f"{uuid.uuid4().hex}.jpg"
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, "JPEG", quality=92)
    (upload_dir() / name).write_bytes(buf.getvalue())
    return f"uploads/{name}"


def test_reaping_fails_running_jobs_and_leaves_queued_ones_alone(Session):
    db = Session()
    db.add_all([Job(id="was-running", user_id="u1", status="running"),
                Job(id="never-started", user_id="u1", status="queued", submitted_payload=PAYLOAD)])
    db.commit()
    assert jobs.reap_orphans(db) == 1
    statuses = {j.id: j.status for j in db.query(Job).all()}
    db.close()
    assert statuses == {"was-running": "failed", "never-started": "queued"}


def test_a_queued_job_is_restarted_from_its_saved_evidence(Session, monkeypatch):
    """Found a real bug: the reloaded image had lost its format, and preflight rejected it."""
    spy = GeminiSpy()
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", spy)
    db = Session()
    db.add(Job(id="queued-1", user_id="u1", status="queued",
               submitted_payload={**PAYLOAD, "image_paths": _saved_photo()}))
    db.commit()
    assert jobs.requeue_pending(db) == 1
    db.close()
    jobs.shutdown(wait=True)

    db = Session()
    job = db.query(Job).filter(Job.id == "queued-1").first()
    db.close()
    assert job.status == "succeeded", job.error
    assert spy.calls == 1


def test_a_queued_job_whose_evidence_is_gone_fails_honestly(Session):
    db = Session()
    db.add(Job(id="queued-2", user_id="u1", status="queued",
               submitted_payload={**PAYLOAD, "image_paths": "uploads/0123456789abcdef.jpg"}))
    db.commit()
    assert jobs.requeue_pending(db) == 0
    job = db.query(Job).filter(Job.id == "queued-2").first()
    db.close()
    assert job.status == "failed" and "no longer stored" in job.error


def test_a_job_dispatched_twice_runs_once(Session, monkeypatch):
    spy = GeminiSpy()
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", spy)
    from platform_backend.services.uploads import load_stored_evidence
    path = _saved_photo()
    db = Session()
    db.add(Job(id="twice", user_id="u1", status="queued", submitted_payload={**PAYLOAD, "image_paths": path}))
    db.commit()
    db.close()
    images, _ = load_stored_evidence(path, "none")
    jobs.run_job("twice", images, [])
    jobs.run_job("twice", images, [])                    # a second dispatch of the same job
    assert spy.calls == 1


def test_evidence_paths_cannot_escape_the_upload_directory():
    from platform_backend.services.uploads import load_stored_evidence
    for hostile in ("uploads/../../etc/passwd", "/etc/passwd", "uploads/a/b.jpg"):
        with pytest.raises(FileNotFoundError):
            load_stored_evidence(hostile, "none")
