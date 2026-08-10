"""
The deterministic decision core.

These are the tests that matter most for the product: they decide claim outcomes, they run
without a model, and they must never regress. Everything here is a pure function, so it is
cheap to cover exhaustively.
"""
from __future__ import annotations

import pytest

from agent_core.agents.alignment import (
    compute_alignment,
    normalise_object,
    normalise_part,
    parts_adjacent,
)
from agent_core.rules_engine import compute_confidence, compute_fraud_score, decide
from agent_core.schemas.perception import (
    ClaimIntent,
    ClaimPerception,
    DamageAnalysis,
    ImageQualityFinding,
    ObservedDamage,
    severity_rank,
)


def make_perception(
    *, claimed_part="front_bumper", claimed_sev="medium", observed=None,
    part_visible=True, observed_object="car", quality="good", quality_score=90,
    issues=None, injection=False,
):
    return ClaimPerception(
        claim_id="C1",
        observed_object=observed_object,
        image_quality=ImageQualityFinding(overall=quality, score=quality_score, issues=issues or []),
        claim_understanding=ClaimIntent(
            object_category="car", claimed_part=claimed_part,
            claimed_issue="dent", claimed_severity=claimed_sev,
        ),
        damage_analysis=DamageAnalysis(
            damage_detected=bool(observed),
            damaged_parts=[
                ObservedDamage(part=p, issue_type="dent", severity=s,
                               image_id="img_1", visual_confidence=85)
                for p, s in (observed or [])
            ],
        ),
        claimed_part_visible=part_visible,
        supporting_image_ids=["img_1"] if observed else [],
        instruction_like_text_present=injection,
    )


# ─── Ontology ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("bonnet", "hood"), ("Hood", "hood"), ("boot", "trunk"),
    ("windscreen", "windshield"), ("wing mirror", "side_mirror"),
    ("front bumper", "front_bumper"), ("left headlight", "headlight"),
    ("display", "screen"), ("touchpad", "trackpad"),
])
def test_synonyms_normalise(given, expected):
    """Without this, 'bonnet dented' vs observed 'hood dent' reads as a mismatch."""
    assert normalise_part(given) == expected


def test_side_does_not_swallow_side_mirror():
    """
    Regression: a bare 'side' -> package_side mapping made a car's side-mirror claim
    normalise to a package part, and the mirror case scored as not_visible.
    """
    assert normalise_part("side_mirror") == "side_mirror"
    assert normalise_part("side mirror") == "side_mirror"


def test_adjacency_is_symmetric():
    assert parts_adjacent("front_bumper", "headlight")
    assert parts_adjacent("headlight", "front_bumper")
    assert not parts_adjacent("front_bumper", "trunk")


def test_object_synonyms():
    assert normalise_object("vehicle") == "car"
    assert normalise_object("notebook") == "laptop"
    assert normalise_object("parcel") == "package"


def test_claimed_severity_scale_exceeds_observed_vocabulary():
    """A claimant can allege 'total loss'; the observed vocabulary tops out at medium."""
    assert severity_rank("total") == 4
    assert severity_rank("high") == 3
    assert severity_rank("medium") == 2
    assert severity_rank("unknown") is None


# ─── Alignment ──────────────────────────────────────────────────────────────

def test_exact_part_match():
    a = compute_alignment(make_perception(observed=[("front_bumper", "medium")]))
    assert a.part_match == "exact"
    assert a.severity_delta == 0


def test_adjacent_part_match():
    a = compute_alignment(make_perception(claimed_part="grille",
                                          observed=[("front_bumper", "medium")]))
    assert a.part_match == "adjacent"


def test_part_mismatch_when_damage_is_elsewhere():
    a = compute_alignment(make_perception(claimed_part="rear_bumper",
                                          observed=[("front_bumper", "medium")]))
    assert a.part_match == "mismatch"


def test_not_visible_is_distinct_from_undamaged():
    """The distinction the whole system turns on."""
    a = compute_alignment(make_perception(part_visible=False, observed=[]))
    assert a.part_match == "not_visible"
    assert a.observed_severity == "unknown"


def test_not_visible_but_adjacent_damage_counts_as_adjacent():
    """
    Regression: a laptop lid reported 'not visible' while the screen it backs is damaged
    was routed to not_enough_information. The region was imaged, so it is an adjacency.
    """
    a = compute_alignment(make_perception(claimed_part="lid", part_visible=False,
                                          observed=[("screen", "low")]))
    assert a.part_match == "adjacent"


def test_severity_inflation_is_measured():
    a = compute_alignment(make_perception(claimed_sev="total",
                                          observed=[("front_bumper", "low")]))
    assert a.severity_delta == 3
    assert a.severity_inflated


def test_object_mismatch_detected():
    a = compute_alignment(make_perception(observed_object="animal", observed=[]))
    assert a.object_match == "mismatch"


# ─── Rules ──────────────────────────────────────────────────────────────────

def test_supported_on_exact_match():
    p = make_perception(observed=[("front_bumper", "medium")])
    v = decide(compute_alignment(p), p)
    assert v.claim_status == "supported"
    assert "R052_supported" in v.rule_ids


def test_severity_inflation_contradicts():
    p = make_perception(claimed_sev="total", observed=[("front_bumper", "low")])
    v = decide(compute_alignment(p), p)
    assert v.claim_status == "contradicted"
    assert "R042_severity_inflation" in v.rule_ids


def test_part_mismatch_contradicts():
    p = make_perception(claimed_part="rear_bumper", observed=[("front_bumper", "medium")])
    v = decide(compute_alignment(p), p)
    assert v.claim_status == "contradicted"
    assert "R040_part_mismatch" in v.rule_ids


def test_part_not_visible_is_never_contradicted():
    p = make_perception(part_visible=False, observed=[])
    v = decide(compute_alignment(p), p)
    assert v.claim_status == "not_enough_information"
    assert "R020_claimed_part_not_visible" in v.rule_ids


def test_wrong_object_beats_the_quality_gate():
    """
    Regression: models rate an off-subject photo as 'unusable' quality, which routed all
    three wrong-object cases to not_enough_information. Recognising a different object is
    a positive finding, so R010 must sit above R003.
    """
    p = make_perception(observed_object="animal", quality="unusable", quality_score=10,
                        observed=[], part_visible=False)
    v = decide(compute_alignment(p), p)
    assert v.claim_status == "contradicted"
    assert "R010_wrong_object" in v.rule_ids


def test_no_usable_image_short_circuits():
    v = decide(None, None, no_usable_image=True)
    assert v.claim_status == "not_enough_information"
    assert "R001_no_usable_image" in v.rule_ids


def test_perception_failure_never_produces_a_verdict():
    v = decide(None, None, perception_failed=True)
    assert v.claim_status == "not_enough_information"
    assert v.confidence == 0
    assert v.manual_review_required


def test_every_verdict_carries_a_rule_id():
    for kwargs in ({"no_usable_image": True}, {"perception_failed": True}):
        assert decide(None, None, **kwargs).rule_ids


def test_decisions_are_reproducible():
    p = make_perception(observed=[("front_bumper", "medium")])
    a = compute_alignment(p)
    assert decide(a, p).to_dict() == decide(a, p).to_dict()


# ─── Fraud and confidence ───────────────────────────────────────────────────

def test_fraud_is_not_assumed():
    p = make_perception(observed=[("front_bumper", "medium")])
    score, signals = compute_fraud_score(compute_alignment(p), p)
    assert score <= 15 and signals == []


def test_fraud_rises_with_objective_signals():
    p = make_perception(claimed_part="rear_bumper", observed=[("front_bumper", "medium")])
    score, signals = compute_fraud_score(compute_alignment(p), p, duplicate_image_reuse=True)
    assert score >= 70
    assert "duplicate_image_reuse" in signals


def test_injection_flag_does_not_by_itself_contradict():
    """A claimant writing 'please approve' is not proof of dishonesty."""
    p = make_perception(observed=[("front_bumper", "medium")], injection=True)
    v = decide(compute_alignment(p), p)
    assert v.claim_status == "supported"
    assert "text_instruction_present" in v.risk_flags
    assert v.manual_review_required


def test_confidence_is_bounded_and_drops_with_quality():
    good = make_perception(observed=[("front_bumper", "medium")])
    poor = make_perception(observed=[("front_bumper", "medium")],
                           quality="poor", quality_score=20, issues=["blurry"])
    c_good = compute_confidence(compute_alignment(good), good)
    c_poor = compute_confidence(compute_alignment(poor), poor)
    assert 0 <= c_poor < c_good <= 100


def test_low_confidence_escalates():
    p = make_perception(part_visible=False, observed=[], quality="poor", quality_score=15)
    v = decide(compute_alignment(p), p)
    assert v.manual_review_required
    assert v.escalation_reason
