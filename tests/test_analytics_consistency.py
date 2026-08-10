"""
The dashboard tile and the list it links to must report the same number.

`/analytics` counted every claim that had *ever* been escalated. The Overview tile rendered
that figure under "Manual Review" with a "View queue" link, and `/queue` lists only claims
still awaiting a decision — so the dashboard said 10 and the queue behind it showed 7. Two
numbers with the same label, one click apart.

`manual_review_claims` keeps its original meaning (how often automation deferred to a human,
which is what the automation rate is derived from). `pending_review_claims` is additive and
defaulted, so no existing consumer changes, and it uses exactly the predicate `/queue` uses.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_backend_pipeline import GeminiSpy


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from platform_backend.db import session as session_module
    from platform_backend.db.models import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'analytics.db'}", connect_args={"check_same_thread": False},
    )
    Testing = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", Testing)

    from platform_backend.services import jobs as job_service
    monkeypatch.setattr(job_service, "SessionLocal", Testing)
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", GeminiSpy())

    from platform_backend.main import app

    def _override():
        db = Testing()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = _override
    with TestClient(app) as c:
        c.SessionLocal = Testing  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    job_service.shutdown(wait=True)


def _seed(client, *, escalated: int, already_decided: int) -> None:
    """Insert claims directly; this is about aggregation, not the pipeline."""
    from platform_backend.db.models import Claim

    db = client.SessionLocal()
    try:
        for i in range(escalated + already_decided):
            db.add(Claim(
                user_id="u1", image_paths="none", user_claim="x", claim_object="car",
                claim_status="not_enough_information", confidence_score=50,
                manual_review_required=True,
                manual_verdict="approved" if i >= escalated else None,
            ))
        db.commit()
    finally:
        db.close()


def test_pending_review_matches_the_queue_length(client):
    _seed(client, escalated=3, already_decided=2)

    kpis = client.get("/analytics").json()["kpis"]
    queue = client.get("/queue").json()

    assert kpis["pending_review_claims"] == len(queue) == 3


def test_manual_review_claims_still_counts_every_escalation(client):
    """
    The historical figure is unchanged — the automation rate is derived from it, and
    "how often did we need a human" should not fall as reviewers work through the queue.
    """
    _seed(client, escalated=3, already_decided=2)

    kpis = client.get("/analytics").json()["kpis"]
    assert kpis["manual_review_claims"] == 5
    assert kpis["pending_review_claims"] == 3


def test_recording_a_verdict_moves_a_claim_out_of_pending(client):
    _seed(client, escalated=2, already_decided=0)

    before = client.get("/analytics").json()["kpis"]
    assert before["pending_review_claims"] == 2

    claim_id = client.get("/queue").json()[0]["id"]
    assert client.post(
        f"/queue/{claim_id}/verdict", json={"verdict": "approved", "notes": "checked"},
    ).status_code == 200

    after = client.get("/analytics").json()["kpis"]
    assert after["pending_review_claims"] == 1
    assert after["manual_review_claims"] == 2      # unchanged: it was still escalated
    assert len(client.get("/queue").json()) == 1


def test_an_empty_database_reports_zero_rather_than_omitting_the_field(client):
    kpis = client.get("/analytics").json()["kpis"]
    assert kpis["pending_review_claims"] == 0
    assert kpis["total_claims"] == 0
