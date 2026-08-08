"""
The no-fabrication guarantee.

The single worst defect found in the Phase 0 audit: when the Gemini API failed, the client
caught the exception and returned a hardcoded `claim_status="supported", confidence=85`.
It fired six times in a three-claim trace. One claim had all four LLM calls return 429 and
still produced a confident approval.

These tests exist so that behaviour cannot come back.
"""
from __future__ import annotations

import pytest

import agent_core.services.gemini_client as gc
from agent_core.schemas.models import DecisionOutput, VisionAnalysisOutput


class _FakeAPIError(Exception):
    """Stands in for google.genai.errors.APIError, which carries .code and .details."""

    def __init__(self, code: int, details: dict | None = None):
        super().__init__(f"{code} error")
        self.code = code
        self.details = details or {}


# ─── The mock fallback must be gone ─────────────────────────────────────────

def test_mock_response_helper_no_longer_exists():
    assert not hasattr(gc, "_get_mock_response"), (
        "_get_mock_response resurrects the fabricated-verdict bug"
    )


def test_client_module_contains_no_hardcoded_verdict_literals():
    """
    Scan executable code only — docstrings and comments legitimately discuss the old bug.

    `ast.unparse` of a docstring-stripped tree drops comments too, leaving just the code.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(gc))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]

    code = ast.unparse(tree)
    for verdict in ("supported", "contradicted"):
        assert f"'{verdict}'" not in code and f'"{verdict}"' not in code, (
            f"the client must never construct a {verdict!r} verdict"
        )


def test_llm_failure_raises_rather_than_returning_a_verdict(monkeypatch):
    """A dead API must produce an exception, never a DecisionOutput."""
    def boom(*a, **kw):
        raise _FakeAPIError(503)

    monkeypatch.setattr(gc, "_get_client", lambda: _Client(boom))
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)

    with pytest.raises(gc.LLMUnavailableError):
        gc.call_gemini_text("prompt", DecisionOutput, cache_key=None)


class _Client:
    def __init__(self, fn):
        self.models = type("M", (), {"generate_content": staticmethod(fn)})()


# ─── The honest error state ─────────────────────────────────────────────────

def test_decision_from_failure_is_not_enough_information():
    d = DecisionOutput.from_failure("the model timed out.")
    assert d.claim_status == "not_enough_information"
    assert d.confidence == 0
    assert d.manual_review_required is True
    assert "timed out" in (d.escalation_reason or "")


def test_decision_from_failure_never_claims_support():
    d = DecisionOutput.from_failure("quota exhausted.")
    assert d.claim_status != "supported"
    assert d.status == "error"


def test_cannot_assess_uses_unknown_not_none():
    """
    'unknown' means we could not look. 'none' means we looked and saw no damage.
    Collapsing them is what turns a missing photo into a contradicted claim.
    """
    from agent_core.agents.vision_analysis import cannot_assess
    v = cannot_assess("no image was supplied.")
    assert v.severity == "unknown"
    assert v.issue_type == "unknown"
    assert v.claimed_part_visible is False
    assert v.supporting_image_ids == []
    assert v.damage_detected is False


# ─── Schema-level enforcement ───────────────────────────────────────────────

def test_decision_rejects_out_of_vocabulary_status():
    with pytest.raises(Exception):
        DecisionOutput(
            status="success", summary="s", confidence=50,
            claim_status="approved",  # not in the contract
            justification="j",
        )


def test_vision_rejects_legacy_severity_vocabulary():
    """`moderate` was the old schema's word. The grader has never accepted it."""
    with pytest.raises(Exception):
        VisionAnalysisOutput(
            status="success", summary="s", confidence=50, damage_detected=True,
            object_part="door", issue_type="dent", severity="moderate",
            impact_direction="left", justification="j",
        )


def test_confidence_is_bounded():
    with pytest.raises(Exception):
        DecisionOutput(
            status="success", summary="s", confidence=150,
            claim_status="supported", justification="j",
        )
