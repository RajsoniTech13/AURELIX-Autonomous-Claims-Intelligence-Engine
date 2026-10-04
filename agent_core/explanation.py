"""
"Why was this claim decided this way?" — answered from the rule that fired, with no model.

A verdict already names its rule (`R040_part_mismatch`) and its fraud signals
(`FRAUD:severity_inflation`); the policy-verification stage names its evidence checks
(`EV-CAR-VISIBILITY`). `knowledge/policies/rule_clause_map.yaml` says which policy clauses
justify each of those. This module joins the two and returns the clause text.

Deliberately deterministic. An explanation of a deterministic decision should be as
reproducible as the decision: the same claim explains the same way every time, costs
nothing, and cannot be talked into saying something the rules did not do. The Policy
Copilot is for open questions; this is for "show me the clause".
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from agent_core.retrieval.policy_corpus import load_rule_clause_map, parse_policy

_RULE_IN_TEXT = re.compile(r"\[(R\d{3}_[a-z_]+)\]")
_EVIDENCE_CHECK = re.compile(r"^EV-([A-Z]+)-([A-Z]+)$")


@lru_cache(maxsize=1)
def _clauses() -> Dict[str, Dict[str, str]]:
    return {c.clause_id: {"clause_id": c.clause_id, "title": c.title, "section": c.section,
                          "text": c.body, "version": c.version} for c in parse_policy()}


@lru_cache(maxsize=1)
def _map() -> Dict[str, Any]:
    return load_rule_clause_map()


def rule_ids_from(decision_rule_ids: Optional[Iterable[str]], justification: str = "") -> List[str]:
    """
    The verdict's rule ids. Prefer the decision audit record; fall back to the `[R0xx_...]`
    tag every justification ends with, for claims stored before the audit record carried ids.
    """
    ids = [str(r) for r in (decision_rule_ids or []) if r]
    if not ids:
        ids = _RULE_IN_TEXT.findall(justification or "")
    return ids


def explain(
    *,
    claim_status: str,
    claim_object: str,
    decision_rule_ids: Iterable[str],
    policy_rule_ids: Iterable[str] = (),
    justification: str = "",
    escalated: bool = False,
) -> Dict[str, Any]:
    mapping = _map()
    entries: List[Dict[str, Any]] = []

    def add(rule_id: str, kind: str, clause_ids: List[str]) -> None:
        entries.append({"rule_id": rule_id, "kind": kind, "clause_ids": clause_ids})

    unmapped: List[str] = []
    for rule_id in rule_ids_from(decision_rule_ids, justification):
        if rule_id.startswith("FRAUD:"):
            signal = rule_id.split(":", 1)[1]
            clause_ids = mapping.get("fraud_signals", {}).get(signal)
            kind = "fraud_signal"
        else:
            clause_ids = mapping.get("rules", {}).get(rule_id)
            kind = "decision_rule"
        if clause_ids:
            add(rule_id, kind, list(clause_ids))
        else:
            unmapped.append(rule_id)

    for rule_id in policy_rule_ids or []:
        m = _EVIDENCE_CHECK.match(str(rule_id))
        clause_ids = mapping.get("evidence_checks", {}).get(m.group(2)) if m else None
        if clause_ids:
            add(str(rule_id), "evidence_check", list(clause_ids))

    if escalated:
        add("escalation", "escalation", list(mapping.get("escalation", [])))
    if claim_status == "supported":
        cover = mapping.get("object_cover", {}).get((claim_object or "").lower())
        if cover:
            add(f"cover:{claim_object.lower()}", "cover", [cover])

    clauses = _clauses()
    cited = []
    for entry in entries:
        for clause_id in entry["clause_ids"]:
            if clause_id not in cited:
                cited.append(clause_id)

    return {
        "claim_status": claim_status,
        "rules": entries,
        "clauses": [clauses[c] for c in cited if c in clauses],
        "unmapped_rule_ids": unmapped,
        "policy_version": mapping.get("version"),
        "model_calls": 0,
    }
