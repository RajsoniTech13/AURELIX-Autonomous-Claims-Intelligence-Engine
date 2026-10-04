"""
Telemetry on the perception path, and the `llm_calls` table behind `/api/v1/metrics/llm`.

The perception call decides claims for the public demo, so the telemetry hook added to it
must be provably inert. These tests drive the **real** `gemini_client` code path — not the
module-level spy the older guardrail tests use — with only the network replaced, and check:

* one claim is still exactly one request, now with exactly one telemetry record;
* a broken telemetry listener cannot change a verdict;
* a cached perception makes zero model calls (an audit gap: "LLM cache has no direct test");
* records carry counts and labels, never claim text;
* the metrics endpoint reports figures computed from rows, linked to the right claim.
"""
from __future__ import annotations

from tests.auth_helpers import auth_headers

import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from agent_core.llm import telemetry
from agent_core.services import gemini_client
from tests.test_backend_pipeline import GeminiSpy, _photo

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakePerceptionGenAI:
    """`genai.Client()` with the network removed: answers perception like GeminiSpy does."""

    def __init__(self):
        self.calls = 0
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, *, model, contents, config):
        self.calls += 1
        ids = GeminiSpy()._requested_ids(contents)
        body = {"results": [GeminiSpy._result(cid) for cid in ids]}
        usage = SimpleNamespace(prompt_token_count=3786, candidates_token_count=420,
                                thoughts_token_count=0)
        return SimpleNamespace(text=json.dumps(body), usage_metadata=usage)


@pytest.fixture
def fake_genai(monkeypatch) -> FakePerceptionGenAI:
    fake = FakePerceptionGenAI()
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake)
    monkeypatch.setattr(gemini_client, "governor", gemini_client.RateGovernor())
    monkeypatch.setattr(gemini_client, "_breaker", gemini_client._CircuitBreaker())
    gemini_client._inmemory_cache.clear()
    yield fake
    gemini_client._inmemory_cache.clear()


def _analyse(tmp_path, request_id="req-1"):
    from agent_core.service import analyse_claim
    photo = _photo(tmp_path)
    return analyse_claim(
        user_id="C1", user_claim="The front bumper is dented.", claim_object="car",
        image_paths=photo.name, image_base_dir=str(tmp_path), request_id=request_id,
    )


# ─── The perception path ────────────────────────────────────────────────────

def test_one_claim_is_still_one_request_and_one_record(fake_genai, tmp_path):
    from agent_core.service import PERCEPTION_PROMPT_VERSION

    with telemetry.collect() as records:
        analysis = _analyse(tmp_path)

    assert fake_genai.calls == 1
    assert analysis.llm_requests == 1
    assert analysis.verdict.claim_status == "supported"
    assert len(records) == 1
    r = records[0]
    assert (r.task, r.provider, r.model, r.outcome) == ("perception", "gemini", "gemini-3.6-flash", "ok")
    assert r.request_id == "req-1"
    assert r.prompt_version == PERCEPTION_PROMPT_VERSION
    assert PERCEPTION_PROMPT_VERSION.startswith("perception@")
    assert (r.input_tokens, r.output_tokens) == (3786, 420)
    assert r.cost_usd == pytest.approx((3786 * 0.75 + 420 * 3.75) / 1e6)


def test_a_broken_listener_cannot_change_a_verdict(fake_genai, tmp_path):
    def explode(_record):
        raise RuntimeError("metrics database is down")

    unsubscribe = telemetry.subscribe(explode)
    try:
        analysis = _analyse(tmp_path)
    finally:
        unsubscribe()
    assert analysis.verdict.claim_status == "supported"
    assert analysis.verdict.rule_ids == ["R052_supported"]


def test_a_cached_perception_makes_zero_model_calls(fake_genai, tmp_path):
    """Closes the audit gap: the cache was implemented but never shown to avoid a call."""
    from agent_core.agents.perception import PreparedClaim, run_batch_perception

    image = Image.open(_photo(tmp_path)).convert("RGB")
    claim = PreparedClaim(claim_id="C1", claim_object="car",
                          claim_text="The front bumper is dented.", images=[image], raw={})

    first = run_batch_perception([claim])
    with telemetry.collect() as records:
        second = run_batch_perception([claim])

    assert fake_genai.calls == 1
    assert gemini_client._quota_ledger.spent_today("gemini-3.6-flash") == 1
    assert second["C1"] == first["C1"]
    assert [(r.cache_hit, r.cost_usd) for r in records] == [(True, 0.0)]


# ─── What a record may contain ──────────────────────────────────────────────

def test_the_calls_table_has_no_column_that_could_hold_claim_text():
    from platform_backend.db.models import LLMCall
    columns = {c.name for c in LLMCall.__table__.columns}
    assert not columns & {"prompt", "prompt_text", "messages", "response", "answer",
                          "content", "user_claim", "text", "question"}


def test_a_record_holds_counts_and_labels_only():
    allowed = {"task", "provider", "model", "outcome", "prompt_version", "input_tokens",
               "output_tokens", "latency_ms", "cost_usd", "cache_hit", "request_id",
               "claim_id", "error_type", "created_at"}
    assert set(telemetry.CallRecord(task="t", provider="p", model="m").to_dict()) == allowed


# ─── Summary arithmetic ─────────────────────────────────────────────────────

@pytest.mark.parametrize("values,p,expected", [
    ([100, 200, 300, 400, 1000], 50, 300),
    ([100, 200, 300, 400, 1000], 95, 1000),
    ([7], 95, 7),
    ([], 50, None),
])
def test_percentile_is_nearest_rank(values, p, expected):
    from platform_backend.services.llm_telemetry import percentile
    assert percentile(values, p) == expected


# ─── End to end through the API ─────────────────────────────────────────────

@pytest.fixture
def api(tmp_path, monkeypatch, fake_genai):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from platform_backend.db import session as session_module
    from platform_backend.db.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                           connect_args={"check_same_thread": False})
    Testing = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", Testing)
    from platform_backend.services import jobs as job_service
    monkeypatch.setattr(job_service, "SessionLocal", Testing)

    from platform_backend.main import app

    def override():
        db = Testing()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override
    with TestClient(app, headers=auth_headers("reviewer")) as client:
        client.Testing = Testing  # type: ignore[attr-defined]
        yield client
    app.dependency_overrides.clear()
    job_service.shutdown(wait=True)


def _jpeg() -> bytes:
    arr = np.random.default_rng(0).integers(40, 215, (620, 900, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


def test_a_submitted_claim_records_its_call_and_links_it_to_the_claim(api, fake_genai):
    from platform_backend.db.models import LLMCall

    response = api.post(
        "/claims/submit-multimodal-stream",
        data={"user_id": "u1", "user_claim": "The front bumper is dented.", "claim_object": "car"},
        files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
    )
    frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    claim = next(f["claim"] for f in frames if f.get("stage") == "done")

    db = api.Testing()
    try:
        calls = db.query(LLMCall).all()
    finally:
        db.close()
    assert fake_genai.calls == 1
    assert len(calls) == 1
    assert (calls[0].task, calls[0].outcome, calls[0].claim_id) == ("perception", "ok", claim["id"])

    metrics = api.get("/api/v1/metrics/llm").json()
    assert metrics["totals"]["calls"] == 1
    assert metrics["cost"]["claims_counted"] == 1
    assert metrics["cost"]["per_claim_usd"] == pytest.approx(calls[0].cost_usd)
    assert metrics["cost"]["billed_usd"] == 0.0
    assert metrics["by_task"]["perception"]["p50_latency_ms"] is not None
    quota = {q["model"]: q for q in metrics["quota"]}
    assert quota["gemini-3.6-flash"]["used_today"] == 1
    # The copilot's Gemini fallback is reported too, so its budget is visible.
    assert "gemini-2.5-flash-lite" in quota


def test_metrics_with_no_traffic_report_nothing_rather_than_zeroes(api):
    metrics = api.get("/api/v1/metrics/llm").json()
    assert metrics["totals"]["calls"] == 0
    assert metrics["latency_ms"]["p50"] is None
    assert metrics["cost"]["per_claim_usd"] is None
    assert metrics["totals"]["cache_hit_rate"] is None


def test_the_app_unsubscribes_its_writer_on_shutdown(api):
    from platform_backend.services import llm_telemetry
    assert llm_telemetry._unsubscribe is not None
