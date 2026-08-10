"""
Object-scoped part resolution, and object normalisation that does not collide.

Both bugs guarded here had the same shape and the same consequence: a **valid claim was
contradicted** — the most damaging error this system can make, because it accuses a
claimant on the strength of a vocabulary collision.

1. `_SYNONYMS` is one flat table, so it can hold only one meaning per token, and the
   meaning it held was the car one. A package claimant writing "side" and a model
   observing "side_panel" both resolved to `quarter_panel` — a car part — which read as a
   part mismatch and fired `R040_part_mismatch`. This is benchmark case SYN-014.

2. `normalise_object` scanned for *any* substring in insertion order, so **"carton"
   resolved to "car"** because "car" is a prefix of it. A carton claim was then judged
   against a vehicle, making `object_match` a mismatch and firing `R010_wrong_object` —
   the most dispositive rule in the engine.

Neither was caught by the existing suite because both tables were only ever exercised with
unambiguous car vocabulary.
"""
from __future__ import annotations

import pytest

from agent_core.agents.alignment import compute_alignment, normalise_object, normalise_part
from agent_core.rules_engine import decide
from tests.test_rules_engine import make_perception  # shared fixture builder


# ─── normalise_object: collisions ───────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("carton", "package"),          # "car" is a prefix — the original bug
    ("cardboard box", "package"),   # "car" is a substring of "cardboard"
    ("cardboard_carton", "package"),
    ("box", "package"),
    ("parcel", "package"),
    ("car", "car"),
    ("suv", "car"),
    ("truck", "car"),
    ("vehicle", "car"),
    ("laptop", "laptop"),
    ("notebook", "laptop"),
    ("laptops", "laptop"),          # plural, resolved by substring fallback
])
def test_object_categories_resolve_without_collision(given, expected):
    assert normalise_object(given) == expected


def test_carton_is_not_a_car():
    """
    The regression in one line.

    A carton judged as a vehicle makes every observed package part a foreign object,
    fires R010_wrong_object, and contradicts the claim outright.
    """
    assert normalise_object("carton") != "car"


# ─── normalise_part: object scoping ─────────────────────────────────────────

@pytest.mark.parametrize("token,expected", [
    ("side", "package_side"),
    ("side panel", "package_side"),
    ("side_panel", "package_side"),
    ("body_panel", "package_side"),
    ("rear_panel", "package_side"),
    ("panel", "package_side"),
    ("wall", "package_side"),
    ("corner", "package_corner"),
    ("lid", "box"),
    ("cover", "box"),
])
def test_package_tokens_resolve_to_package_parts(token, expected):
    assert normalise_part(token, "package") == expected


@pytest.mark.parametrize("token,expected", [
    ("side", "quarter_panel"),
    ("body", "quarter_panel"),
    ("panel", "quarter_panel"),
    ("side_panel", "quarter_panel"),
])
def test_car_tokens_resolve_to_car_parts(token, expected):
    assert normalise_part(token, "car") == expected


@pytest.mark.parametrize("token", ["side_panel", "body_panel", "rear_panel"])
def test_laptop_panels_do_not_leak_to_a_car_part(token):
    assert normalise_part(token, "laptop") == "body"


def test_exact_keys_still_win_over_the_object_overlay():
    """
    The overlay must not shadow a specific name. A car's "side mirror" is a mirror even
    though bare "side" now maps to the flank — this is the failure the original
    no-bare-side comment was written to prevent, and it must stay prevented.
    """
    assert normalise_part("side_mirror", "car") == "side_mirror"
    assert normalise_part("side mirror", "car") == "side_mirror"
    assert normalise_part("front_bumper", "car") == "front_bumper"
    assert normalise_part("windscreen", "car") == "windshield"


def test_omitting_the_object_preserves_the_previous_global_behaviour():
    """Existing callers and tests pass no object; they must be unaffected."""
    assert normalise_part("side_panel") == "quarter_panel"
    assert normalise_part("bonnet") == "hood"


# ─── End to end: the verdict that was wrong ─────────────────────────────────

def test_a_package_side_claim_is_supported_not_contradicted():
    """
    SYN-014 end to end. Claimant says "side", model observes "side_panel" on a package.

    Before object scoping both sides resolved to `quarter_panel`, which is not a package
    part at all — yet they resolved to the *same* wrong thing only by accident of table
    order. The claimant's bare "side" did not resolve, so the pair read as a mismatch and
    the claim was contradicted.
    """
    p = make_perception(claimed_part="side", claimed_sev="low",
                   observed=[("side_panel", "low")], observed_object="package")
    p.claim_understanding.object_category = "package"

    alignment = compute_alignment(p, "package")
    assert alignment.part_match == "exact", alignment.notes
    assert alignment.matched_part == "package_side"

    verdict = decide(alignment, p)
    assert verdict.claim_status == "supported"
    assert "R040_part_mismatch" not in verdict.rule_ids


def test_a_genuine_package_part_mismatch_is_still_contradicted():
    """
    The guard on the guard: scoping must not make every package claim agree with itself.
    A seal-tampering claim against observed corner damage stays a mismatch — they are
    deliberately not adjacent, being different failure modes.
    """
    p = make_perception(claimed_part="seal", claimed_sev="medium",
                   observed=[("package_corner", "medium")], observed_object="package")
    p.claim_understanding.object_category = "package"

    alignment = compute_alignment(p, "package")
    assert alignment.part_match == "mismatch"
    assert decide(alignment, p).claim_status == "contradicted"


def test_a_carton_claim_is_not_treated_as_a_wrong_object():
    """
    The object-collision bug end to end: a valid carton claim must not be contradicted by
    R010 merely because "carton" starts with "car".
    """
    p = make_perception(claimed_part="corner", claimed_sev="low",
                   observed=[("package_corner", "low")], observed_object="carton")
    p.claim_understanding.object_category = "carton"

    alignment = compute_alignment(p, "carton")
    assert alignment.object_match == "match"

    verdict = decide(alignment, p)
    assert "R010_wrong_object" not in verdict.rule_ids
    assert verdict.claim_status == "supported"


def test_a_real_wrong_object_is_still_caught():
    """Correct contradiction detection is preserved — a cat is still not a car."""
    p = make_perception(claimed_part="front_bumper", observed=[("front_bumper", "medium")],
                   observed_object="animal")
    alignment = compute_alignment(p, "car")
    assert alignment.object_match == "mismatch"

    verdict = decide(alignment, p)
    assert verdict.claim_status == "contradicted"
    assert "R010_wrong_object" in verdict.rule_ids
