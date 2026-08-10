"""
AURELIX — the frozen output contract.

`agent_core/output/output.csv` is a public schema. Its column names, their order, and the
value vocabulary of each column are fixed by the grader. Nothing in this file may change
without a corresponding change to the grader, and `tests/test_output_contract.py` will fail
loudly if it does.

Every vocabulary below was extracted from `agent_core/data/sample_claims.csv` — the file the
predictions are actually scored against — not from a docstring or a prompt. Where the code
previously disagreed with this file, the code was wrong.
"""
from __future__ import annotations

from typing import Literal

# ─── Column order (14 columns, exact) ────────────────────────────────────────

OUTPUT_COLUMNS: tuple[str, ...] = (
    "user_id",
    "image_paths",
    "user_claim",
    "claim_object",
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
)


# ─── Closed vocabularies ─────────────────────────────────────────────────────

ClaimStatus = Literal["supported", "contradicted", "not_enough_information"]
CLAIM_STATUS_VALUES: frozenset[str] = frozenset(("supported", "contradicted", "not_enough_information"))

# NOTE: the ground truth uses none/low/medium/unknown. The old Pydantic schemas documented
# none/minor/moderate/severe, which intersects the scored vocabulary on exactly one value.
# The scored vocabulary wins.
Severity = Literal["none", "low", "medium", "unknown"]
SEVERITY_VALUES: frozenset[str] = frozenset(("none", "low", "medium", "unknown"))

IssueType = Literal[
    "dent", "scratch", "crack", "broken_part", "stain",
    "crushed_packaging", "torn_packaging", "water_damage",
    "none", "unknown",
]
ISSUE_TYPE_VALUES: frozenset[str] = frozenset(
    ("dent", "scratch", "crack", "broken_part", "stain",
     "crushed_packaging", "torn_packaging", "water_damage", "none", "unknown")
)

# Observed across car / laptop / package claims, plus the sentinels.
OBJECT_PART_VALUES: frozenset[str] = frozenset((
    # car
    "front_bumper", "rear_bumper", "windshield", "side_mirror", "door", "hood", "headlight",
    # laptop
    "screen", "keyboard", "hinge", "trackpad", "body", "corner", "lid",
    # package
    "package_corner", "package_side", "seal", "box", "contents", "label",
    # sentinels
    "none", "unknown",
))

# Closed set. `none` is mutually exclusive with every other flag.
RISK_FLAG_VALUES: frozenset[str] = frozenset((
    "none",
    "claim_mismatch",
    "user_history_risk",
    "manual_review_required",
    "wrong_angle",
    "damage_not_visible",
    "blurry_image",
    "possible_manipulation",
    "cropped_or_obstructed",
    "text_instruction_present",
))

BOOL_VALUES: frozenset[str] = frozenset(("true", "false"))

NO_SUPPORTING_IMAGES = "none"
MULTI_VALUE_SEPARATOR = ";"


# ─── Image IDs are 1-based ───────────────────────────────────────────────────
#
# The contract uses img_1, img_2, ... The code used to emit img_0, img_1, ... which made
# every populated `supporting_image_ids` cell off by one against the grader.

def image_id(index: int) -> str:
    """Map a 0-based list position to the contract's 1-based image id."""
    if index < 0:
        raise ValueError(f"image index must be non-negative, got {index}")
    return f"img_{index + 1}"


def image_id_index(image_id_str: str) -> int:
    """Inverse of `image_id`: 'img_1' -> 0. Raises on anything malformed."""
    if not image_id_str.startswith("img_"):
        raise ValueError(f"malformed image id: {image_id_str!r}")
    return int(image_id_str[4:]) - 1


# ─── Normalisation helpers ───────────────────────────────────────────────────

def to_bool_str(value: bool) -> str:
    """Booleans render as lowercase 'true'/'false' in the CSV, never 'True'/'False'."""
    return "true" if value else "false"


def join_multi(values: list[str], empty: str = "none") -> str:
    """Render a multi-value cell. Empty renders as the column's sentinel, not ''."""
    return MULTI_VALUE_SEPARATOR.join(values) if values else empty


def normalise_risk_flags(flags: list[str]) -> list[str]:
    """
    Reduce an arbitrary flag list to the frozen vocabulary.

    Drops out-of-vocabulary flags, de-duplicates, drops `none` when any real flag is
    present, and returns a stable (sorted) order so output is deterministic.
    """
    kept = {f for f in flags if f in RISK_FLAG_VALUES}
    kept.discard("none")
    return sorted(kept)


def coerce_to_vocabulary(value: str, allowed: frozenset[str], fallback: str) -> str:
    """
    Last line of defence at the CSV boundary.

    The Pydantic `Literal` types are the primary enforcement — Gemini's `response_schema`
    rejects out-of-vocabulary values before they reach us. This exists so that a
    hand-built dict or a future schema drift degrades to a valid sentinel rather than
    writing a value the grader cannot parse.
    """
    v = (value or "").strip().lower()
    return v if v in allowed else fallback
