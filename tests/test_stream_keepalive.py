"""
The SSE stream must keep sending bytes while the model is thinking.

This is a deployment property, not a cosmetic one. The pipeline emits nothing between
`perception:running` and `perception:complete`, and that gap *is* the model call — measured
at ~12s on free quota and **185s** under per-minute rate-limit backoff. Every reverse proxy
in front of a deployed API closes a response that has sent no bytes for its idle timeout
(~100s on Render). The analysis then completes server-side, having spent one of twenty
daily requests, and the user watches a page that never finishes.

An SSE comment (`: keepalive`) fixes it: bytes on the wire, discarded by the browser's
parser, no client handler fires.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List

import pytest

from platform_backend.services import claim_service


class _SlowPipeline:
    """Stands in for `analyse_claim_events` with a long silence in the middle."""

    def __init__(self, silence: float):
        self.silence = silence

    def __call__(self, **kwargs: Any) -> Iterator[Dict[str, Any]]:
        yield {"stage": "preflight", "status": "complete"}
        yield {"stage": "perception", "status": "running"}
        time.sleep(self.silence)
        yield {"stage": "perception", "status": "complete"}
        yield {"stage": "done", "analysis": "sentinel"}


def _drain(monkeypatch, silence: float, heartbeat: float) -> List[Any]:
    monkeypatch.setattr(claim_service, "analyse_claim_events", _SlowPipeline(silence))
    monkeypatch.setattr(claim_service, "HEARTBEAT_SECONDS", heartbeat)
    return list(claim_service._events_with_heartbeat(user_id="u1"))


def test_a_long_silence_produces_keepalives(monkeypatch):
    """
    Half a second of silence against a 0.1s heartbeat: the stream must not go quiet.

    Without this the wire is empty for the entire model call.
    """
    events = _drain(monkeypatch, silence=0.5, heartbeat=0.1)
    beats = [e for e in events if e is claim_service._HEARTBEAT]
    assert beats, "no keepalive was emitted during the silence"


def test_keepalives_do_not_disturb_the_real_events(monkeypatch):
    """A keepalive is a comment. It must not add, drop, or reorder a single stage."""
    events = _drain(monkeypatch, silence=0.4, heartbeat=0.1)
    real = [e for e in events if e is not claim_service._HEARTBEAT]

    assert [(e["stage"], e.get("status")) for e in real] == [
        ("preflight", "complete"),
        ("perception", "running"),
        ("perception", "complete"),
        ("done", None),
    ]


def test_no_keepalive_when_the_pipeline_is_prompt(monkeypatch):
    """A fast claim should not be padded with noise."""
    events = _drain(monkeypatch, silence=0.0, heartbeat=5.0)
    assert claim_service._HEARTBEAT not in events


def test_a_failure_on_the_worker_thread_reaches_the_caller(monkeypatch):
    """
    The pipeline now runs on a worker thread. An exception that stays there would turn a
    hard failure into a stream that simply stops — the worst of both outcomes, because the
    client cannot tell it apart from success.
    """
    def _explode(**kwargs: Any) -> Iterator[Dict[str, Any]]:
        yield {"stage": "preflight", "status": "complete"}
        raise RuntimeError("perception exploded")

    monkeypatch.setattr(claim_service, "analyse_claim_events", _explode)
    monkeypatch.setattr(claim_service, "HEARTBEAT_SECONDS", 0.1)

    with pytest.raises(RuntimeError, match="perception exploded"):
        list(claim_service._events_with_heartbeat(user_id="u1"))


def test_the_sse_frame_for_a_keepalive_is_a_comment(monkeypatch):
    """
    `: keepalive` — a colon-prefixed line is an SSE comment. If this were emitted as
    `data:` the client's event handler would fire with an unparseable payload, and the
    frontend would try to read `event.stage` off it.
    """
    monkeypatch.setattr(claim_service, "analyse_claim_events", _SlowPipeline(0.4))
    monkeypatch.setattr(claim_service, "HEARTBEAT_SECONDS", 0.1)

    class _NullSession:
        def add(self, *a, **k): pass
        def commit(self): pass
        def refresh(self, *a, **k): pass

    monkeypatch.setattr(claim_service, "_analysis_to_db_claim", lambda *a, **k: object())
    monkeypatch.setattr(claim_service, "_audit_logs_for", lambda *a, **k: [])
    monkeypatch.setattr(
        claim_service, "_save_claim_and_audit",
        lambda db, claim, logs: _FakeClaim(),
    )

    frames = list(claim_service.generate_claim_stream(
        db=_NullSession(), user_id="u1", image_paths="none", user_claim="x",
        claim_object="car", u_history=None, e_rules=None,
    ))

    keepalives = [f for f in frames if f.startswith(":")]
    assert keepalives, "expected at least one comment frame"
    assert all(f == ": keepalive\n\n" for f in keepalives)
    for frame in keepalives:
        assert "data:" not in frame


class _FakeClaim:
    id = 1
    user_id = "u1"
    image_paths = "none"
    user_claim = "x"
    claim_object = "car"
    claim_status = "supported"
    claim_status_justification = "ok"
    confidence_score = 90
    manual_review_required = False
    escalation_reason = None
    policy_status = "PASS"
    policy_reason = ""
    issue_type = "dent"
    object_part = "front_bumper"
    severity = "minor"
    impact_direction = None
    drivable_status = True
    supporting_image_ids = "img_1"
    fraud_score = 0
    user_risk_score = 0
    risk_level = "LOW"
    risk_flags = "none"
    created_at = None
    audit_logs: list = []
