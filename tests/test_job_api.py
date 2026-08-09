"""
The asynchronous claim-submission contract.

What these tests protect is the property that made the change worth making: **submission
returns before the analysis finishes**. Everything else — idempotency, cursor paging,
orphan reaping — exists because an async contract without them leaks work, duplicates
charges against a 20-request daily budget, or hides claims from a review queue.

Hermetic: a temporary SQLite database per test and a stubbed perception call. No model,
no network.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.test_backend_pipeline import GeminiSpy

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh app bound to a throwaway database, with perception stubbed."""
    from platform_backend.db import session as session_module
    from platform_backend.db.models import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False},
    )
    Testing = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", Testing)

    from platform_backend.services import jobs as job_service
    monkeypatch.setattr(job_service, "SessionLocal", Testing)
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", GeminiSpy())

    from platform_backend.api import v1
    from platform_backend.main import app

    def override_db():
        db = Testing()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_db
    monkeypatch.setattr(v1.job_service, "SessionLocal", Testing)

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    job_service.shutdown(wait=True)


def photo_bytes() -> bytes:
    """Sharp, well-exposed, large enough to clear the quality gate."""
    rng = np.random.default_rng(0)
    arr = rng.integers(40, 215, (620, 900, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


def form(**overrides):
    data = {"user_id": "u1", "user_claim": "The front bumper is dented.", "claim_object": "car"}
    data.update(overrides)
    return data


def wait_for_terminal(client, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# ─── The contract ───────────────────────────────────────────────────────────

def test_submission_returns_202_with_a_job_rather_than_a_verdict(client):
    """The whole point: the response arrives before the analysis does."""
    r = client.post("/api/v1/claims", data=form(),
                    files={"files": ("claim.jpg", photo_bytes(), "image/jpeg")})
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"]
    assert body["status"] in ("queued", "running")
    assert body["claim_id"] is None
    assert r.headers["Location"] == f"/api/v1/jobs/{body['job_id']}"


def test_polling_reaches_a_finished_claim(client):
    job_id = client.post("/api/v1/claims", data=form(),
                         files={"files": ("claim.jpg", photo_bytes(), "image/jpeg")}
                         ).json()["job_id"]
    done = wait_for_terminal(client, job_id)
    assert done["status"] == "succeeded", done.get("error")
    assert done["claim_id"] is not None

    claim = client.get(f"/api/v1/claims/{done['claim_id']}").json()
    assert claim["claim_status"] == "supported"


def test_progress_records_every_pipeline_stage(client):
    from agent_core.service import PIPELINE_STAGES

    job_id = client.post("/api/v1/claims", data=form(),
                         files={"files": ("claim.jpg", photo_bytes(), "image/jpeg")}
                         ).json()["job_id"]
    done = wait_for_terminal(client, job_id)
    completed = [p["stage"] for p in done["progress"] if p.get("status") == "complete"]
    assert completed == list(PIPELINE_STAGES)


def test_the_event_stream_reports_progress_and_terminates(client):
    job_id = client.post("/api/v1/claims", data=form(),
                         files={"files": ("claim.jpg", photo_bytes(), "image/jpeg")}
                         ).json()["job_id"]

    payloads = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/stream") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))

    assert payloads, "the stream produced nothing"
    assert payloads[-1]["status"] == "succeeded"
    assert payloads[-1]["claim_id"] is not None


# ─── Idempotency ────────────────────────────────────────────────────────────

def test_a_retried_submission_does_not_spend_a_second_request(client):
    """
    A double-tapped button must not cost a second request out of a 20-per-day budget,
    nor create a duplicate claim record.
    """
    headers = {"Idempotency-Key": "retry-me"}
    first = client.post("/api/v1/claims", data=form(), headers=headers,
                        files={"files": ("claim.jpg", photo_bytes(), "image/jpeg")})
    assert first.status_code == 202

    second = client.post("/api/v1/claims", data=form(), headers=headers,
                         files={"files": ("claim.jpg", photo_bytes(), "image/jpeg")})
    assert second.status_code == 200            # nothing new was accepted
    assert second.json()["idempotent_replay"] is True
    assert second.json()["job_id"] == first.json()["job_id"]


def test_idempotency_keys_are_scoped_per_user(client):
    """Otherwise one claimant's key silently returns another claimant's claim."""
    headers = {"Idempotency-Key": "shared"}
    a = client.post("/api/v1/claims", data=form(user_id="u1"), headers=headers,
                    files={"files": ("a.jpg", photo_bytes(), "image/jpeg")})
    b = client.post("/api/v1/claims", data=form(user_id="u2"), headers=headers,
                    files={"files": ("b.jpg", photo_bytes(), "image/jpeg")})
    assert b.status_code == 202
    assert b.json()["job_id"] != a.json()["job_id"]


# ─── Failure paths ──────────────────────────────────────────────────────────

def test_a_malformed_upload_fails_fast_with_400(client):
    """
    Rejected at submission, not asynchronously. A job that fails for a reason the submitter
    never sees is worse than a synchronous error.
    """
    r = client.post("/api/v1/claims", data=form(),
                    files={"files": ("not-an-image.jpg", b"plain text", "image/jpeg")})
    assert r.status_code == 400
    assert "not a readable image" in r.json()["detail"]


def test_a_claim_with_no_usable_image_still_completes_honestly(client):
    job_id = client.post("/api/v1/claims", data=form()).json()["job_id"]
    done = wait_for_terminal(client, job_id)
    assert done["status"] == "succeeded"
    claim = client.get(f"/api/v1/claims/{done['claim_id']}").json()
    assert claim["claim_status"] == "not_enough_information"


def test_unknown_ids_are_404_not_500(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404
    assert client.get("/api/v1/claims/999999").status_code == 404
    assert client.get("/api/v1/jobs/nope/stream").status_code == 404


def test_interrupted_jobs_are_failed_not_left_running(client, tmp_path):
    """
    A single-process pool cannot resume a job across a restart. Leaving it `running` means
    a client polls it forever and no operator ever finds out.
    """
    from platform_backend.db.models import Job
    from platform_backend.services.jobs import reap_orphans
    from platform_backend.db import session as session_module

    db = session_module.SessionLocal()
    try:
        db.add(Job(id="stuck", user_id="u1", status="running"))
        db.commit()
        assert reap_orphans(db) >= 1
        stuck = db.query(Job).filter(Job.id == "stuck").first()
        assert stuck.status == "failed"
        assert "Interrupted" in stuck.error
    finally:
        db.close()


# ─── Pagination ─────────────────────────────────────────────────────────────

def test_cursor_pagination_walks_every_claim_exactly_once(client):
    for _ in range(5):
        job_id = client.post("/api/v1/claims", data=form()).json()["job_id"]
        wait_for_terminal(client, job_id)

    seen, cursor, pages = [], None, 0
    while pages < 10:
        params = {"limit": 2}
        if cursor is not None:
            params["after"] = cursor
        body = client.get("/api/v1/claims", params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if not body["has_more"]:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5, "cursor paging repeated a claim"
