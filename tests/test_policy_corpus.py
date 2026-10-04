"""
The policy corpus and its map to the decision rules.

The copilot is only as trustworthy as the document it cites, and the explanation endpoint
only as complete as the rule-to-clause map. These tests make both properties structural:

* every clause parses, with a stable id, an `applies_to` line and a contextual header;
* every decision rule, fraud signal and evidence check maps to clauses that exist;
* the policy wording agrees with the evidence-requirements CSV the live system reads —
  it would be worse than useless for the copilot to cite a rule the system does not apply.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
import yaml

from agent_core.retrieval.policy_corpus import (
    DEFAULT_POLICY,
    build_policy_clauses,
    load_rule_clause_map,
    parse_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_EVIDENCE_CSV = REPO_ROOT / "agent_core" / "data" / "evidence_requirements.csv"


@pytest.fixture(scope="module")
def clauses():
    return parse_policy()


@pytest.fixture(scope="module")
def clause_ids(clauses):
    return {c.clause_id for c in clauses}


def test_the_policy_has_25_to_35_uniquely_identified_clauses(clauses):
    ids = [c.clause_id for c in clauses]
    assert 25 <= len(ids) <= 35
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Z]{3}-\d+", i) for i in ids)


def test_every_clause_is_labelled_and_has_a_body(clauses):
    for c in clauses:
        assert c.applies_to, c.clause_id
        assert set(c.applies_to) <= {"all", "car", "laptop", "package"}, c.clause_id
        assert len(c.body.split()) >= 20, f"{c.clause_id} is too thin to answer anything"
        assert c.version == "1.0" and c.effective_date == "2026-10-01"


def test_each_chunk_carries_its_place_in_the_document(clauses):
    exc2 = next(c for c in clauses if c.clause_id == "EXC-2")
    assert exc2.text.startswith("AURELIX Protection Policy v1.0 › Part 3 — Exclusions › EXC-2 Wear and tear\n")


def test_the_synthetic_disclaimer_is_not_indexed_as_a_clause(clauses):
    assert not any("SYNTHETIC POLICY WORDING" in c.text for c in clauses)


def test_the_document_declares_itself_synthetic():
    head = DEFAULT_POLICY.read_text(encoding="utf-8").split("---")[1]
    assert yaml.safe_load(head)["synthetic"] is True


def test_a_content_change_changes_the_hash_and_nothing_else_does(tmp_path):
    original = DEFAULT_POLICY.read_text(encoding="utf-8")
    edited = tmp_path / "policy.md"
    edited.write_text(original.replace("rust, fading", "rust, peeling paint, fading"), encoding="utf-8")
    before = {c.clause_id: c.content_hash for c in parse_policy(DEFAULT_POLICY)}
    after = {c.clause_id: c.content_hash for c in parse_policy(edited)}
    assert [cid for cid in before if before[cid] != after[cid]] == ["EXC-2"]


def test_clauses_become_documents_tagged_as_clauses():
    docs = build_policy_clauses()
    assert {d.metadata["kind"] for d in docs} == {"clause"}
    assert all(d.metadata["content_hash"] and d.metadata["version"] == "1.0" for d in docs)


@pytest.mark.parametrize("broken,error", [
    ("### DEF-1 · Claim\napplies_to: all\n", "duplicate clause ids"),
    ("### DEF-9 · No label\n\nSome text without an applies_to line.\n", "no applies_to"),
])
def test_authoring_errors_fail_the_build(tmp_path, broken, error):
    doc = tmp_path / "policy.md"
    doc.write_text(DEFAULT_POLICY.read_text(encoding="utf-8") + "\n" + broken, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        parse_policy(doc)


# ─── The rule-to-clause map ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mapping():
    return load_rule_clause_map()


def test_every_decision_rule_is_justified_by_a_clause(mapping, clause_ids):
    rules = yaml.safe_load((REPO_ROOT / "config" / "decision_rules.yaml").read_text())["rules"]
    missing = [r["id"] for r in rules if r["id"] not in mapping["rules"]]
    assert not missing, f"rules with no justifying clause: {missing}"
    for rule_id, cited in mapping["rules"].items():
        assert cited, rule_id
        assert set(cited) <= clause_ids, f"{rule_id} cites unknown clauses {set(cited) - clause_ids}"


def test_the_map_names_no_rule_that_does_not_exist(mapping):
    rules = {r["id"] for r in yaml.safe_load((REPO_ROOT / "config" / "decision_rules.yaml").read_text())["rules"]}
    assert set(mapping["rules"]) <= rules


def test_every_fraud_signal_is_justified(mapping, clause_ids):
    signals = yaml.safe_load((REPO_ROOT / "config" / "decision_rules.yaml").read_text())["fraud"]["signals"]
    assert set(signals) == set(mapping["fraud_signals"])
    for cited in mapping["fraud_signals"].values():
        assert set(cited) <= clause_ids


def test_every_evidence_check_suffix_is_justified(mapping, clause_ids):
    # The suffixes `build_policy_rules` and `policy_verification` emit: EV-<OBJECT>-<SUFFIX>.
    assert set(mapping["evidence_checks"]) == {"COUNT", "VISIBILITY", "ANGLE", "TYPE"}
    assert set(mapping["escalation"]) <= clause_ids
    for cited in mapping["evidence_checks"].values():
        assert set(cited) <= clause_ids


# ─── The wording agrees with what the system enforces ───────────────────────

@pytest.fixture(scope="module")
def live_requirements():
    with LIVE_EVIDENCE_CSV.open(encoding="utf-8") as f:
        return {row["claim_object"]: row for row in csv.DictReader(f)}


def test_every_object_the_system_handles_has_a_cover_clause(mapping, live_requirements, clause_ids):
    assert set(live_requirements) == set(mapping["object_cover"])
    assert set(mapping["object_cover"].values()) <= clause_ids


def test_the_photo_minimum_in_the_policy_matches_the_live_csv(clauses, live_requirements):
    """EVD-1 says one photograph for every object. The file the system reads must agree."""
    evd1 = next(c for c in clauses if c.clause_id == "EVD-1").body
    assert "One photograph is the minimum for a car, a laptop and a package" in evd1
    assert {obj: row["required_image_count"] for obj, row in live_requirements.items()} == \
        {"car": "1", "laptop": "1", "package": "1"}


def test_every_covered_part_the_system_checks_is_named_in_the_policy(clauses, live_requirements):
    """DEF-4 must list exactly the parts `policy_verification` treats as covered."""
    def4 = next(c for c in clauses if c.clause_id == "DEF-4").body.lower()
    for obj, row in live_requirements.items():
        for part in row["required_visibility"].split(";"):
            assert part.replace("_", " ") in def4, f"{obj} part {part!r} is enforced but not in DEF-4"
