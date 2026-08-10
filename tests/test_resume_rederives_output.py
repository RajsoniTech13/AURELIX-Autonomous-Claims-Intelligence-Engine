"""
A resumed run must re-derive the CSV, not replay a frozen copy of it.

`output.csv` is the graded contract and `results_detail.json` is the evidence behind it.
They are produced by the same run and must describe the same verdicts.

They did not. On a resumed run the detail file was rebuilt by replaying `judge()` over the
stored perception — correctly picking up any rule or ontology change — while the CSV fell
back to `normalized_result`, the row frozen into the checkpoint when the claim was *first*
analysed. So fixing a rule and re-running produced an evaluation report showing the new
verdicts and a CSV still carrying the old ones, with the stale artifact being the one that
gets graded.

Caught for real: the object-scoped ontology fix moved SYN-014 from `contradicted` to
`supported` in `results_detail.json` while `output.csv` stayed byte-identical to the
pre-fix commit.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = REPO_ROOT / "agent_core/output/output.csv"
RESULTS_JSON = REPO_ROOT / "agent_core/output/results_detail.json"

pytestmark = pytest.mark.skipif(
    not (OUTPUT_CSV.exists() and RESULTS_JSON.exists()),
    reason="benchmark artifacts not present",
)


def _csv_rows():
    with OUTPUT_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _detail():
    return json.loads(RESULTS_JSON.read_text(encoding="utf-8"))


def test_the_two_artifacts_cover_the_same_claims():
    assert len(_csv_rows()) == len(_detail())


def test_verdict_totals_agree_between_csv_and_detail():
    """
    The check that would have failed before the fix: the CSV said 19/17/8 while the detail
    file said 20/16/8, because one had been re-derived and the other had not.
    """
    from collections import Counter

    csv_counts = Counter(r["claim_status"] for r in _csv_rows())
    detail_counts = Counter(d["verdict"]["claim_status"] for d in _detail())
    assert csv_counts == detail_counts, (
        f"output.csv and results_detail.json disagree: {csv_counts} vs {detail_counts}. "
        "A resumed run has written a stale CSV."
    )


def test_every_csv_verdict_is_inside_the_frozen_vocabulary():
    from agent_core.schemas.contract import CLAIM_STATUS_VALUES

    for row in _csv_rows():
        assert row["claim_status"] in CLAIM_STATUS_VALUES


def test_no_package_claim_is_scored_against_a_car_part():
    """
    The ontology regression, asserted on the deliverable rather than in a unit test.
    `quarter_panel` is a car part; it must never appear on a package row.
    """
    offenders = [
        r for r in _csv_rows()
        if r["claim_object"] == "package" and r["object_part"] == "quarter_panel"
    ]
    assert not offenders, f"package rows resolved to a car part: {offenders}"
