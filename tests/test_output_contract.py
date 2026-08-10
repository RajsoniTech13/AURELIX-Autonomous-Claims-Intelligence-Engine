"""
Golden tests for the frozen `output.csv` contract.

If any of these fail, the grader's parser breaks. They are here to make that impossible to
do by accident.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from agent_core.service import judge, to_output_row
from agent_core.schemas.contract import (
    ISSUE_TYPE_VALUES,
    OUTPUT_COLUMNS,
    RISK_FLAG_VALUES,
    SEVERITY_VALUES,
    image_id,
    image_id_index,
    normalise_risk_flags,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = REPO_ROOT / "agent_core" / "data" / "sample_claims.csv"

# The exact header, byte for byte. Do not "fix" this to match the code — the code must
# match this.
GOLDEN_HEADER = (
    "user_id,image_paths,user_claim,claim_object,evidence_standard_met,"
    "evidence_standard_met_reason,risk_flags,issue_type,object_part,claim_status,"
    "claim_status_justification,supporting_image_ids,valid_image,severity"
)


def test_header_is_frozen():
    assert ",".join(OUTPUT_COLUMNS) == GOLDEN_HEADER
    assert len(OUTPUT_COLUMNS) == 14


def _row(raw_claim: dict, **entry) -> dict:
    """Render a judged claim. Both the CLI and the API reach the CSV through this pair."""
    return to_output_row(judge({
        "claim_id": "c", "row": raw_claim, "perception": None, **entry,
    }))


def test_built_row_has_exactly_the_contract_columns():
    assert list(_row({"user_id": "u1"}).keys()) == list(OUTPUT_COLUMNS)


def test_a_failed_claim_still_produces_a_complete_valid_row():
    """
    A short-circuited or crashed claim must still yield a full row.

    The regression this guards: main.py used to raise KeyError on partial state, swallow
    it, and skip the claim entirely — turning 44 failures into an empty output file.
    """
    row = _row({"user_id": "u1", "claim_object": "car"}, no_usable_image=True)
    assert row["claim_status"] == "not_enough_information"
    assert row["severity"] == "unknown"
    assert row["valid_image"] == "false"
    assert row["supporting_image_ids"] == "none"
    assert all(v != "" for k, v in row.items() if k not in ("image_paths", "user_claim"))


def test_no_cell_is_ever_empty_string_for_vocabulary_columns():
    row = _row({}, perception_failed=True)
    for col in ("issue_type", "object_part", "severity", "claim_status",
                "risk_flags", "supporting_image_ids", "valid_image", "evidence_standard_met"):
        assert row[col].strip(), f"{col} must never be blank"


# ─── Vocabulary conformance against the file that is actually graded ─────────

def _sample_rows():
    with SAMPLE_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("column,allowed", [
    ("severity", SEVERITY_VALUES),
    ("issue_type", ISSUE_TYPE_VALUES),
])
def test_contract_vocabulary_covers_ground_truth(column, allowed):
    """Our declared vocabulary must be a superset of what the grader actually uses."""
    observed = {r[column].strip().lower() for r in _sample_rows()}
    assert observed <= allowed, f"ground truth uses {observed - allowed} for {column}"


def test_risk_flag_vocabulary_covers_ground_truth():
    observed = set()
    for r in _sample_rows():
        observed |= {f.strip() for f in r["risk_flags"].split(";") if f.strip()}
    assert observed <= RISK_FLAG_VALUES, f"unknown flags in ground truth: {observed - RISK_FLAG_VALUES}"


def test_severity_vocabulary_matches_ground_truth_exactly():
    """
    Guards the specific mismatch found in the audit: the schemas documented
    none/minor/moderate/severe while the grader scores none/low/medium/unknown.
    """
    assert SEVERITY_VALUES == {"none", "low", "medium", "unknown"}
    assert "minor" not in SEVERITY_VALUES
    assert "moderate" not in SEVERITY_VALUES


# ─── Image ids are 1-based ──────────────────────────────────────────────────

def test_image_ids_are_one_based():
    """The contract uses img_1 for the first image. The code used to emit img_0."""
    assert image_id(0) == "img_1"
    assert image_id(1) == "img_2"
    assert image_id_index("img_1") == 0
    assert image_id_index(image_id(7)) == 7


def test_ground_truth_never_contains_img_0():
    for r in _sample_rows():
        assert "img_0" not in r["supporting_image_ids"]


# ─── Risk flag normalisation ────────────────────────────────────────────────

def test_out_of_vocabulary_flags_are_dropped():
    """user_risk.py used to emit these straight into the CSV; the grader can't parse them."""
    out = normalise_risk_flags(["high_rejection_rate", "user_history_risk", "frequent_manual_reviews"])
    assert out == ["user_history_risk"]


def test_none_is_dropped_when_real_flags_present():
    assert normalise_risk_flags(["none", "blurry_image"]) == ["blurry_image"]
    assert normalise_risk_flags(["none"]) == []


def test_risk_flags_are_deduplicated_and_deterministic():
    a = normalise_risk_flags(["blurry_image", "user_history_risk", "blurry_image"])
    b = normalise_risk_flags(["user_history_risk", "blurry_image"])
    assert a == b == ["blurry_image", "user_history_risk"]
