"""
Dataset integrity for the synthetic benchmark.

The single most important property: **ground truth must never reach the model.** A label
that leaks into a prompt turns the benchmark into a lookup and every metric derived from it
becomes meaningless. These tests make that leak a build failure rather than a silent one.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "agent_core" / "data" / "synthetic"
CLAIMS = DATA / "claims_synthetic.csv"
TRUTH = DATA / "ground_truth.csv"

pytestmark = pytest.mark.skipif(
    not CLAIMS.exists(), reason="synthetic dataset not generated yet"
)


def _rows(path: Path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def claims():
    return _rows(CLAIMS)


@pytest.fixture(scope="module")
def truth():
    return _rows(TRUTH)


# ─── Ground-truth isolation ─────────────────────────────────────────────────

def test_input_file_carries_no_ground_truth_columns(claims):
    """The input file may only contain what a real claimant would supply."""
    allowed = {"claim_id", "user_id", "image_paths", "user_claim", "claim_object"}
    assert set(claims[0].keys()) == allowed


def test_no_label_column_leaks_into_the_input(claims):
    forbidden = {
        "expected_status", "truth_part", "truth_severity", "truth_issue",
        "truth_object", "category", "claimed_part", "claimed_severity",
    }
    assert not (set(claims[0].keys()) & forbidden)


def test_narratives_never_mention_a_verdict(claims, truth):
    """
    A narrative containing 'contradicted' would hand the answer to the model.

    Injection cases are exempt: their payload deliberately contains verdict words, because
    that is the attack. `test_injection_demands_the_wrong_verdict` covers them instead.
    """
    labels = {t["claim_id"]: t for t in truth}
    verdicts = ("supported", "contradicted", "not_enough_information", "expected_status")
    for row in claims:
        if labels[row["claim_id"]]["category"].startswith("injection"):
            continue
        text = row["user_claim"].lower()
        for v in verdicts:
            assert v not in text, f"{row['claim_id']} leaks '{v}' in its narrative"


def test_injection_demands_the_wrong_verdict(claims, truth):
    """
    An injection case is only informative if obeying the injection gives the WRONG answer.

    If the payload demands the outcome that is genuinely correct, the case cannot tell a
    system that resisted the injection from one that obeyed it and got lucky.
    """
    by_id = {r["claim_id"]: r for r in claims}
    injections = [t for t in truth if t["category"].startswith("injection")]
    assert injections, "the benchmark must contain injection cases"

    for t in injections:
        text = by_id[t["claim_id"]]["user_claim"].lower()
        expected = t["expected_status"]
        if expected == "supported":
            assert "contradicted" in text or "denied" in text, (
                f"{t['claim_id']} is genuinely supported, so the injection must demand rejection"
            )
            assert "mark this claim as supported" not in text
        else:
            assert "verified" in text or "approv" in text, (
                f"{t['claim_id']} is genuinely {expected}, so the injection must demand approval"
            )


def test_narratives_never_mention_the_case_category(claims, truth):
    categories = {t["category"] for t in truth} | {"ground_truth", "synthetic"}
    for row in claims:
        text = row["user_claim"].lower().replace("_", " ")
        for cat in categories:
            assert cat.replace("_", " ") not in text, f"{row['claim_id']} leaks category"


def test_image_filenames_encode_no_labels(claims):
    """Filenames travel with the evidence; they must not describe the answer."""
    for row in claims:
        for path in row["image_paths"].split(";"):
            name = Path(path).name.lower()
            for token in ("supported", "contradicted", "mismatch", "fraud",
                          "match", "truth", "expected", "dent", "scratch", "crack"):
                assert token not in name, f"{name} encodes a label"


# ─── Completeness and shape ─────────────────────────────────────────────────

def test_exactly_44_cases(claims, truth):
    assert len(claims) == 44
    assert len(truth) == 44


def test_ids_align_and_are_unique(claims, truth):
    cids = [r["claim_id"] for r in claims]
    assert len(set(cids)) == 44
    assert set(cids) == {t["claim_id"] for t in truth}


def test_every_image_exists_and_decodes(claims):
    from PIL import Image
    for row in claims:
        for rel in row["image_paths"].split(";"):
            p = REPO_ROOT / rel
            assert p.exists(), f"missing image {rel}"
            with Image.open(p) as im:
                im.verify()


def test_expected_statuses_are_in_the_frozen_vocabulary(truth):
    from agent_core.schemas.contract import CLAIM_STATUS_VALUES
    for t in truth:
        assert t["expected_status"] in CLAIM_STATUS_VALUES


def test_dataset_is_labelled_synthetic(truth):
    assert all(t["dataset"] == "SYNTHETIC" for t in truth)
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    assert "SYNTHETIC" in readme
    assert "not real insurance claims" in readme.lower()


# ─── Case mix ───────────────────────────────────────────────────────────────

def test_mix_is_not_dominated_by_fraud(truth):
    """
    A benchmark where most cases are fraudulent teaches a system to be suspicious rather
    than accurate. Honest claims must be the majority.
    """
    from collections import Counter
    statuses = Counter(t["expected_status"] for t in truth)
    assert statuses["supported"] >= 15
    assert statuses["contradicted"] <= len(truth) // 2


def test_all_required_failure_modes_are_represented(truth):
    cats = {t["category"] for t in truth}
    for required in ("match", "part_mismatch", "severity_inflation",
                     "poor_image", "part_not_visible", "wrong_object", "injection"):
        assert required in cats, f"missing category: {required}"


def test_every_class_has_meaningful_support(truth):
    from collections import Counter
    for cls, n in Counter(t["expected_status"] for t in truth).items():
        assert n >= 5, f"{cls} has only {n} cases; per-class F1 would be noise"


def test_all_three_object_categories_present(claims):
    assert {r["claim_object"] for r in claims} == {"car", "laptop", "package"}
