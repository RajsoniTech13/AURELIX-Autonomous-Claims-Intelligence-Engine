"""
The two places where the model's dialect met the system's dialect and lost.

Gemini reports parts the way a person writes them — "front bumper", "bonnet",
"driver door". Two components then compared that raw text against a **canonical**
vocabulary using exact or substring membership:

1. `policy_verification` checked `claimed_part` against the CSV's
   `required_visibility` list. `"front_bumper" in "front bumper"` is false and so
   is the reverse, so **every naturally-worded part produced a WARNING** — 20 of
   34 claims in the live database, on claims whose evidence was fully compliant.
   A reviewer reading "not listed in visibility requirements" on a perfectly good
   front-bumper claim learns nothing and distrusts the next warning too.

2. `to_output_row` coerced `chosen.part` straight into the frozen
   `OBJECT_PART_VALUES`. Same mismatch, quieter failure: the part silently became
   `unknown` in `output.csv` and on the claim record — a real observation
   discarded at the boundary.

Both are fixed by consulting the ontology that already knew the answer. These
tests pin that, and pin the boundary: a part that is *named but not covered*
still warns, because that is what a coverage check is for.
"""
from __future__ import annotations

import pytest

from agent_core.agents.alignment import normalise_part
from agent_core.agents.policy_verification import run_policy_verification_agent
from agent_core.schemas.contract import OBJECT_PART_VALUES, coerce_to_vocabulary


def policy(part: str, obj: str = "car", images: str = "uploads/a.jpg"):
    return run_policy_verification_agent(
        claim_object=obj, claimed_part=part, image_paths=images,
        image_valid=True, image_issues=[],
    )


# ─── Policy: the words people actually use must pass ────────────────────────

@pytest.mark.parametrize("part", [
    "front bumper", "Front Bumper", "front_bumper", "FRONT BUMPER",
    "rear bumper", "side mirror", "driver door",
])
def test_naturally_worded_parts_do_not_warn(part):
    """The regression: these all produced WARNING on fully compliant claims."""
    assert policy(part).status == "PASS", f"{part!r} wrongly warned"


@pytest.mark.parametrize("part,canonical", [
    ("bonnet", "hood"), ("windscreen", "windshield"), ("wing mirror", "side_mirror"),
])
def test_synonyms_resolve_to_the_covered_part(part, canonical):
    """The ontology knows these; policy simply was not asking it."""
    assert normalise_part(part, "car") == canonical
    assert policy(part).status == "PASS"


def test_an_unnamed_part_is_not_a_policy_failure():
    """
    No part named means no visibility requirement to fail. R021 already routes
    unspecified claims to review; warning here double-counted the same fact.
    """
    for part in ("unknown", "none", "", "  "):
        assert policy(part).status == "PASS", f"{part!r} wrongly warned"


# ─── Policy: genuine coverage gaps must still warn ──────────────────────────

@pytest.mark.parametrize("part", ["roof", "spoiler", "exhaust", "wheel"])
def test_a_named_part_outside_the_covered_list_still_warns(part):
    """
    The guard on the guard. Fixing the false positives must not silence the
    check — the car policy covers bumpers, windshield, mirror, door and hood, and
    a claim naming anything else is genuinely outside it.
    """
    result = policy(part)
    assert result.status == "WARNING"
    assert "EV-CAR-VISIBILITY" in result.rule_ids


def test_the_warning_says_the_evidence_itself_is_fine():
    """
    Wording matters here: the old reason implied the *evidence* was deficient.
    It is not — the photographs met every requirement; it is the part that may
    fall outside cover, which is a different conversation with the claimant.
    """
    reason = policy("roof").reason
    assert "evidence itself meets requirements" in reason.lower()


def test_missing_images_still_fails_regardless_of_part_wording():
    """Count is checked before visibility; a compliant part cannot rescue it."""
    result = policy("front bumper", images="")
    assert result.status == "FAIL"
    assert "EV-CAR-COUNT" in result.rule_ids


# ─── Policy is object-scoped too ────────────────────────────────────────────

def test_package_wording_resolves_against_the_package_policy():
    assert policy("side", obj="package").status == "PASS"
    assert policy("outer box", obj="package").status == "PASS"


def test_a_car_part_claimed_on_a_package_policy_warns():
    assert policy("windshield", obj="package").status == "WARNING"


# ─── The frozen output contract ─────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("front bumper", "front_bumper"),
    ("Front Bumper", "front_bumper"),
    ("bonnet", "hood"),
    ("windscreen", "windshield"),
    ("side mirror", "side_mirror"),
    ("driver door", "door"),
])
def test_observed_parts_survive_the_csv_boundary(raw, expected):
    """
    Previously every one of these coerced to "unknown": a real observation lost
    between the model and the graded file.
    """
    assert coerce_to_vocabulary(normalise_part(raw, "car"), OBJECT_PART_VALUES, "unknown") == expected


def test_an_unresolvable_part_still_degrades_to_the_sentinel():
    """Normalisation must not become a way to smuggle values past the contract."""
    assert coerce_to_vocabulary(
        normalise_part("flux capacitor", "car"), OBJECT_PART_VALUES, "unknown",
    ) == "unknown"


# ─── End to end: an honest claim must look honest ───────────────────────────

def test_a_textbook_claim_produces_a_clean_record():
    """
    The complaint that started this: a claim that is right in every respect
    should not carry a warning, a flag, or an escalation.
    """
    from agent_core.agents.alignment import compute_alignment
    from agent_core.agents.document_check import run_document_check
    from agent_core.rules_engine import decide
    from tests.test_rules_engine import make_perception

    p = make_perception(
        claimed_part="front bumper", claimed_sev="medium",
        observed=[("front bumper", "medium")], quality="good", quality_score=95,
    )
    alignment = compute_alignment(p, "car")
    docs = run_document_check(p, alignment, "car")
    verdict = decide(alignment, p, document_signals=docs.signals)

    assert policy("front bumper").status == "PASS"
    assert alignment.part_match == "exact"
    assert alignment.severity_delta == 0
    assert verdict.claim_status == "supported"
    assert verdict.manual_review_required is False
    assert verdict.risk_flags == []
    assert verdict.rule_ids == ["R052_supported"]
