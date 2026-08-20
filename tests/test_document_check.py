"""
Document cross-check: the paperwork half of a claim.

Photographs answer "is there damage". Paperwork answers "is this the damage
being paid for", and the gap between the two is where most real claim leakage
sits. These tests pin the three comparisons that gap is checkable with, and —
more importantly — pin the boundary: the model transcribes, Python judges.

The whole capability costs **zero additional model requests**: documents ride in
the same multimodal call as the photographs. `test_documents_cost_no_extra_
requests` is the guard on that, because it is the only reason this fits a
20-request daily budget.
"""
from __future__ import annotations

import pytest

from agent_core.agents.alignment import compute_alignment
from agent_core.agents.document_check import run_document_check
from agent_core.rules_engine import decide
from agent_core.schemas.perception import DocumentFinding
from tests.test_rules_engine import make_perception


def doc(**kw) -> DocumentFinding:
    base = dict(
        document_id="doc_1", document_type="repair_estimate", legible=True,
        object_described="car", line_items=[], total_amount=None,
        currency="GBP", document_date="unknown", issuer="unknown",
        named_party="unknown", reference="unknown", notes=[],
    )
    base.update(kw)
    return DocumentFinding(**base)


def analyse(perception, claim_object="car"):
    alignment = compute_alignment(perception, claim_object)
    return alignment, run_document_check(perception, alignment, claim_object)


# ─── Nothing to check ───────────────────────────────────────────────────────

def test_no_documents_produces_no_signals():
    p = make_perception(observed=[("front_bumper", "medium")])
    _, result = analyse(p)
    assert result.count == 0
    assert result.signals == []


def test_a_claim_with_no_perception_is_not_a_crash():
    assert run_document_check(None, None, "car").count == 0


# ─── Object consistency ─────────────────────────────────────────────────────

def test_an_invoice_for_a_different_object_contradicts_the_claim():
    """
    A laptop screen invoice attached to a car claim. Cheap to submit, and
    previously invisible because nothing read the paperwork.
    """
    p = make_perception(observed=[("front_bumper", "medium")])
    p.documents = [doc(object_described="laptop", line_items=["LCD panel replacement"])]

    alignment, result = analyse(p)
    assert result.object_mismatch
    assert "document_object_mismatch" in result.signals

    verdict = decide(alignment, p, document_signals=result.signals)
    assert verdict.claim_status == "contradicted"
    assert "R043_document_wrong_object" in verdict.rule_ids


def test_a_matching_object_raises_nothing():
    p = make_perception(observed=[("front_bumper", "medium")])
    p.documents = [doc(object_described="car", line_items=["front bumper respray"])]
    _, result = analyse(p)
    assert not result.object_mismatch
    assert "document_object_mismatch" not in result.signals


def test_an_unstated_object_is_not_held_against_the_claimant():
    """`unknown` is the absence of a reading, not a mismatch."""
    p = make_perception(observed=[("front_bumper", "medium")])
    p.documents = [doc(object_described="unknown")]
    _, result = analyse(p)
    assert not result.object_mismatch


# ─── Part consistency ───────────────────────────────────────────────────────

def test_an_estimate_for_the_observed_part_supports_the_claim():
    p = make_perception(observed=[("front_bumper", "medium")])
    p.documents = [doc(line_items=["Replace front bumper", "Paint and refinish"])]

    _, result = analyse(p)
    assert result.assessments[0].part_support == "supports"
    assert "front_bumper" in result.assessments[0].matched_parts
    assert result.signals == []


def test_an_estimate_for_a_part_the_photograph_does_not_show_is_flagged():
    """
    The classic inflated repair: damage on the bumper, an invoice for a door.
    """
    p = make_perception(claimed_part="front_bumper", observed=[("front_bumper", "medium")])
    p.documents = [doc(line_items=["Replace driver door", "Door skin"])]

    _, result = analyse(p)
    assert result.part_contradiction
    assert "document_part_contradiction" in result.signals


def test_a_part_contradiction_alone_does_not_contradict_a_photographed_claim():
    """
    The guard that keeps this honest.

    If the photograph confirms the claimed part, paperwork naming something else
    is a flag for a human — not grounds to overturn what the camera recorded.
    R044 requires the visual evidence to be inconclusive too.
    """
    p = make_perception(claimed_part="front_bumper", observed=[("front_bumper", "medium")])
    p.documents = [doc(line_items=["Replace driver door"])]

    alignment, result = analyse(p)
    assert alignment.part_match == "exact"

    verdict = decide(alignment, p, document_signals=result.signals)
    assert "R044_document_part_contradiction" not in verdict.rule_ids
    assert verdict.claim_status == "supported"


def test_a_part_contradiction_does_contradict_when_the_photographs_disagree_too():
    p = make_perception(claimed_part="front_bumper", observed=[("rear_bumper", "medium")])
    p.documents = [doc(line_items=["Replace tailgate"])]

    alignment, result = analyse(p)
    assert alignment.part_match == "mismatch"

    verdict = decide(alignment, p, document_signals=result.signals)
    assert verdict.claim_status == "contradicted"


def test_part_matching_uses_the_object_scoped_ontology():
    """
    A package invoice reading "side panel" must resolve to a package part, not a
    car's quarter panel — the same collision that once contradicted a valid claim.
    """
    p = make_perception(
        claimed_part="side", observed=[("side_panel", "low")], observed_object="package",
    )
    p.claim_understanding.object_category = "package"
    p.documents = [doc(object_described="package", line_items=["Replace outer side panel"])]

    _, result = analyse(p, "package")
    assert "package_side" in result.assessments[0].matched_parts
    assert result.assessments[0].part_support == "supports"


# ─── Amount plausibility ────────────────────────────────────────────────────

def test_a_large_quote_against_light_damage_is_flagged():
    p = make_perception(claimed_part="front_bumper", observed=[("front_bumper", "low")])
    p.documents = [doc(total_amount=9_000.0, line_items=["Front bumper"])]

    _, result = analyse(p)
    assert "document_amount_implausible" in result.signals


def test_a_proportionate_quote_is_not_flagged():
    p = make_perception(claimed_part="front_bumper", observed=[("front_bumper", "low")])
    p.documents = [doc(total_amount=600.0, line_items=["Front bumper"])]

    _, result = analyse(p)
    assert "document_amount_implausible" not in result.signals


def test_a_police_report_is_not_measured_as_a_quote():
    """A reference number is not a price. Only invoices and estimates are costed."""
    p = make_perception(observed=[("front_bumper", "low")])
    p.documents = [doc(document_type="police_report", total_amount=999_999.0)]

    _, result = analyse(p)
    assert "document_amount_implausible" not in result.signals


def test_an_amount_is_not_judged_when_severity_could_not_be_read():
    p = make_perception(claimed_part="front_bumper", observed=[("front_bumper", "unknown")])
    p.documents = [doc(total_amount=50_000.0)]
    _, result = analyse(p)
    assert "document_amount_implausible" not in result.signals


# ─── Illegible ──────────────────────────────────────────────────────────────

def test_an_unreadable_document_is_reported_not_guessed():
    p = make_perception(observed=[("front_bumper", "medium")])
    p.documents = [doc(document_type="unreadable", legible=False)]

    _, result = analyse(p)
    assert result.illegible
    assert result.signals == []          # unreadable is not an accusation
    assert "could not be read" in result.describe()


# ─── The cost guarantee ─────────────────────────────────────────────────────

def test_documents_cost_no_extra_requests(tmp_path, monkeypatch):
    """
    The property the whole feature depends on: documents ride in the *same*
    multimodal call as the photographs. If this ever becomes a second request,
    a claim costs two of twenty daily and the capability stops being free.
    """
    import io
    import numpy as np
    from PIL import Image

    from tests.test_backend_pipeline import GeminiSpy
    from agent_core.service import analyse_claim

    rng = np.random.default_rng(0)
    arr = rng.integers(40, 215, (620, 900, 3), dtype=np.uint8)
    path = tmp_path / "claim.jpg"
    Image.fromarray(arr, "RGB").save(path, "JPEG", quality=92)

    spy = GeminiSpy(claim_id="C1")
    monkeypatch.setattr("agent_core.agents.perception.call_gemini_multimodal", spy)

    analysis = analyse_claim(
        user_id="C1", user_claim="The front bumper is dented.", claim_object="car",
        image_paths="claim.jpg", image_base_dir=str(tmp_path), claim_id="C1",
        documents=[b"%PDF-1.4 fake", b"%PDF-1.4 also fake"],
    )

    assert spy.calls == 1, "documents must not trigger a second model request"
    assert analysis.llm_requests == 1


def test_document_findings_are_isolated_per_claim():
    """
    A document finding attributed to a claim that did not supply it is the same
    contamination signature as a stray image id — and more dangerous, because an
    invoice carries a real amount and a real name.
    """
    from agent_core.agents.perception import PreparedClaim, BatchIsolationError, validate_isolation
    from agent_core.schemas.perception import BatchPerceptionOutput

    claims = [PreparedClaim("C1", "car", "text", images=[], documents=[b"x"])]
    payload = {
        "results": [{
            "claim_id": "C1", "observed_object": "car",
            "image_quality": {"overall": "good", "score": 90, "issues": []},
            "claim_understanding": {
                "object_category": "car", "claimed_part": "front_bumper",
                "claimed_issue": "dent", "claimed_severity": "medium",
            },
            "damage_analysis": {"damage_detected": False, "damaged_parts": []},
            "claimed_part_visible": False,
            "documents": [{
                "document_id": "doc_7", "document_type": "invoice", "legible": True,
                "object_described": "car",
            }],
        }]
    }
    with pytest.raises(BatchIsolationError, match="doc_7"):
        validate_isolation(BatchPerceptionOutput.model_validate(payload), claims)
