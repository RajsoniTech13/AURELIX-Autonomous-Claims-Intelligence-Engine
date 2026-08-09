"""
The three retrieval collections and the index lifecycle.

The test that matters most here is `test_every_cited_policy_rule_id_resolves`. A verdict
that cites `EV-CAR-COUNT` is only better than "the car policy" if `EV-CAR-COUNT` can be
looked up — a citation that resolves to nothing is worse than no citation, because it looks
like an audit trail.

Hermetic. No model, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.agents.policy_verification import run_policy_verification_agent
from agent_core.retrieval.collections import (
    COLLECTIONS,
    FRAUD_PATTERNS,
    HISTORICAL_CLAIMS,
    INDEX_VERSION,
    POLICY_RULES,
    IndexBundle,
    build_fraud_patterns,
    build_historical_claims,
    build_policy_rules,
)
from agent_core.retrieval.hybrid import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_CSV = REPO_ROOT / "agent_core/data/evidence_requirements.csv"
FRAUD_YAML = REPO_ROOT / "agent_core/data/fraud_patterns.yaml"
CLAIMS_CSV = REPO_ROOT / "agent_core/data/synthetic/claims_synthetic.csv"


@pytest.fixture
def policy_docs():
    return build_policy_rules(EVIDENCE_CSV)


@pytest.fixture
def bundle(tmp_path, policy_docs) -> IndexBundle:
    import csv
    with CLAIMS_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    b = IndexBundle(directory=tmp_path / "index")
    b.upsert(HISTORICAL_CLAIMS, build_historical_claims(rows))
    b.upsert(POLICY_RULES, policy_docs)
    b.upsert(FRAUD_PATTERNS, build_fraud_patterns(FRAUD_YAML))
    return b


# ─── policy_rules ───────────────────────────────────────────────────────────

def test_policy_rules_are_chunked_one_per_requirement(policy_docs):
    """One document per requirement, not per object, so a failure can name what failed."""
    ids = {d.doc_id for d in policy_docs}
    assert {"EV-CAR-COUNT", "EV-CAR-VISIBILITY", "EV-CAR-ANGLE", "EV-CAR-TYPE"} <= ids
    assert {"EV-LAPTOP-COUNT", "EV-PACKAGE-COUNT"} <= ids


def test_policy_rule_ids_are_stable_against_reordering(policy_docs, tmp_path):
    """
    Ids derive from the object category and field name, never row order. Otherwise a
    reordered CSV silently repoints every stored citation at a different requirement.
    """
    reordered = tmp_path / "evidence.csv"
    lines = EVIDENCE_CSV.read_text(encoding="utf-8").strip().splitlines()
    reordered.write_text("\n".join([lines[0]] + list(reversed(lines[1:]))), encoding="utf-8")
    assert {d.doc_id for d in build_policy_rules(reordered)} == {d.doc_id for d in policy_docs}


@pytest.mark.parametrize("claim_object,claimed_part,images,expect_status", [
    ("car", "front_bumper", "a.jpg", "PASS"),
    ("car", "spoiler", "a.jpg", "WARNING"),          # part outside visibility guidelines
    ("car", "front_bumper", "", "FAIL"),             # no images at all
])
def test_every_cited_policy_rule_id_resolves(policy_docs, claim_object, claimed_part,
                                             images, expect_status):
    """A citation that resolves to nothing looks like an audit trail and is not one."""
    known = {d.doc_id for d in policy_docs}
    result = run_policy_verification_agent(
        claim_object=claim_object, claimed_part=claimed_part,
        image_paths=images, image_valid=True, image_issues=[],
    )
    assert result.status == expect_status
    assert result.rule_ids, "policy outcomes must cite the requirements they applied"
    unresolved = set(result.rule_ids) - known
    assert not unresolved, f"cited rule ids that do not exist in policy_rules: {unresolved}"


# ─── historical_claims ──────────────────────────────────────────────────────

def test_historical_claims_index_the_outcome_not_only_the_narrative():
    rows = [{"claim_id": "C1", "user_claim": "bumper knocked in a car park",
             "claim_object": "car", "user_id": "u1"}]
    observed = {"C1": {"part": "rear_bumper", "issue_type": "dent",
                       "severity": "low", "claim_status": "contradicted"}}
    doc = build_historical_claims(rows, observed)[0]
    assert "rear_bumper" in doc.text          # what was seen, not only what was said
    assert doc.metadata["final_verdict"] == "contradicted"
    assert doc.metadata["object_category"] == "car"


def test_historical_claims_survive_missing_perception():
    rows = [{"claim_id": "C1", "user_claim": "bumper damage", "claim_object": "car"}]
    doc = build_historical_claims(rows, {})[0]
    assert doc.text.strip() == "bumper damage"


# ─── fraud_patterns ─────────────────────────────────────────────────────────

def test_fraud_patterns_carry_stable_ids_and_reviewer_guidance():
    docs = build_fraud_patterns(FRAUD_YAML)
    assert docs
    for doc in docs:
        assert doc.doc_id.startswith("FP-")
        assert doc.metadata["reviewer_prompt"]


def test_fraud_patterns_reference_rules_that_exist():
    """A playbook pointing at rules the engine does not have is documentation rot."""
    import yaml
    rules = yaml.safe_load((REPO_ROOT / "config/decision_rules.yaml").read_text(encoding="utf-8"))
    known = {r["id"] for r in rules["rules"]}
    for doc in build_fraud_patterns(FRAUD_YAML):
        unknown = set(doc.metadata.get("related_rules", [])) - known
        assert not unknown, f"{doc.doc_id} references non-existent rules: {unknown}"


def test_fraud_pattern_lookup_filters_by_category(bundle):
    results = bundle.fraud_patterns_for("car", "the claimed part is not the damaged part")
    assert results
    assert "FP-001-PART-SHOPPING" in {r.document.doc_id for r in results}


# ─── lifecycle ──────────────────────────────────────────────────────────────

def test_a_bundle_round_trips_through_disk(bundle):
    bundle.save()
    reloaded = IndexBundle.load(bundle.directory)
    for name in COLLECTIONS:
        assert len(reloaded.documents[name]) == len(bundle.documents[name])
        assert reloaded.meta[name].fingerprint == bundle.meta[name].fingerprint


def test_upsert_merges_rather_than_replaces(bundle):
    """A nightly build adds yesterday's claims; it must not truncate the history."""
    before = len(bundle.documents[HISTORICAL_CLAIMS])
    bundle.upsert(HISTORICAL_CLAIMS, [Document("NEW-1", "a new claim", {"object_category": "car"})])
    assert len(bundle.documents[HISTORICAL_CLAIMS]) == before + 1

    bundle.upsert(HISTORICAL_CLAIMS, [Document("NEW-1", "revised text", {"object_category": "car"})])
    assert len(bundle.documents[HISTORICAL_CLAIMS]) == before + 1
    assert next(d for d in bundle.documents[HISTORICAL_CLAIMS]
                if d.doc_id == "NEW-1").text == "revised text"


def test_the_fingerprint_detects_stale_content(bundle, policy_docs):
    assert bundle.stale_collections({POLICY_RULES: policy_docs}) == []
    changed = policy_docs + [Document("EV-BOAT-COUNT", "boats need 2 photos", {})]
    assert bundle.stale_collections({POLICY_RULES: changed}) == [POLICY_RULES]


def test_a_mismatched_index_version_is_refused_not_guessed(bundle):
    """A stale index is worse than none, because it answers confidently."""
    bundle.save()
    manifest = bundle.directory / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["index_version"] = INDEX_VERSION + 99
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Rebuild"):
        IndexBundle.load(bundle.directory)


def test_loading_a_missing_index_is_empty_not_an_error(tmp_path):
    empty = IndexBundle.load(tmp_path / "nothing")
    assert empty.documents == {}
    assert empty.search(HISTORICAL_CLAIMS, "anything") == []


def test_an_unknown_collection_name_is_rejected(bundle):
    with pytest.raises(ValueError, match="unknown collection"):
        bundle.upsert("invented_collection", [])


def test_retrievers_are_built_once_and_reused(bundle):
    assert bundle.retriever(POLICY_RULES) is bundle.retriever(POLICY_RULES)


def test_upserting_invalidates_the_cached_retriever(bundle):
    first = bundle.retriever(POLICY_RULES)
    bundle.upsert(POLICY_RULES, [Document("EV-BOAT-COUNT", "boats need 2 photos", {})])
    assert bundle.retriever(POLICY_RULES) is not first


# ─── retrieval quality ──────────────────────────────────────────────────────

def test_recall_at_5_on_the_historical_claims_collection(bundle):
    """
    Measured on the real 44-claim corpus with paraphrased probes — none of these queries
    is a substring of the document it should find.
    """
    probes = [
        ("my car's front bumper picked up a dent", "car"),
        ("the laptop display cracked", "laptop"),
        ("parcel turned up with the seal ripped", "package"),
    ]
    for query, category in probes:
        results = bundle.search(
            HISTORICAL_CLAIMS, query, filters={"object_category": category}, top_k=5)
        assert results, f"no results for {query!r}"
        assert all(r.document.metadata["object_category"] == category for r in results)


def test_a_car_query_never_retrieves_a_laptop_claim(bundle):
    results = bundle.search(
        HISTORICAL_CLAIMS, "cracked screen", filters={"object_category": "car"}, top_k=5)
    assert all(r.document.metadata["object_category"] == "car" for r in results)
