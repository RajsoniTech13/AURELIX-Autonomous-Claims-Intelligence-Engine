"""
The single place where pipeline state becomes an `output.csv` row.

There used to be two copies of this logic, ~120 lines apart in `main.py`, and both read
state keys the graph does not produce (`quality`, `compliance`, `escalation`). Every claim
raised `KeyError`, was swallowed by a bare `except`, and was skipped — so the CLI wrote a
header and nothing else.

Everything here is defensive by design: a partially-populated state (short-circuit, failed
branch) must still yield a complete, valid row. A missing field degrades to the column's
sentinel; it never raises and never blanks a cell.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent_core.schemas.contract import (
    ISSUE_TYPE_VALUES,
    OBJECT_PART_VALUES,
    SEVERITY_VALUES,
    CLAIM_STATUS_VALUES,
    coerce_to_vocabulary,
    join_multi,
    normalise_risk_flags,
    to_bool_str,
)


def _is_failed(section: Dict[str, Any]) -> bool:
    return section.get("status") == "failed"


def build_output_row(state: Dict[str, Any], raw_claim: Dict[str, str]) -> Dict[str, str]:
    """
    Map a final graph state onto the frozen 14-column contract.

    `raw_claim` supplies the four passthrough columns verbatim, so the input echo in the
    output file is byte-identical to what was read.
    """
    decision = state.get("decision") or {}
    vision = state.get("vision") or {}
    policy = state.get("policy") or {}
    validation = state.get("image_validation") or {}
    user_risk = state.get("user_risk") or {}
    fraud = state.get("fraud") or {}

    # ── evidence_standard_met ──
    # PASS means the evidence met policy. WARNING and FAIL do not. A policy branch that
    # failed to run cannot certify anything, so it reads as not met.
    policy_status = policy.get("status")
    evidence_met = policy_status == "PASS"
    evidence_reason = (
        policy.get("reason")
        or policy.get("summary")
        or "Policy verification did not complete for this claim."
    )

    # ── valid_image ──
    valid_image = bool(validation.get("valid", False))

    # ── risk_flags ──
    # Union of every contributing source, reduced to the frozen vocabulary. Out-of-
    # vocabulary flags are dropped rather than written, because the grader cannot parse
    # them; the detail survives in the audit log.
    collected: List[str] = []
    collected += validation.get("risk_flags", []) or []
    collected += user_risk.get("risk_flags", []) or []
    if "text_injection" in (fraud.get("fraud_flags") or []):
        collected.append("text_instruction_present")
    if vision.get("claimed_part_visible") is False and valid_image:
        # We had usable images and still could not see the claimed part.
        collected.append("damage_not_visible")
    if decision.get("manual_review_required"):
        collected.append("manual_review_required")

    risk_flags = normalise_risk_flags(collected)

    # ── vision-derived columns ──
    issue_type = coerce_to_vocabulary(vision.get("issue_type", ""), ISSUE_TYPE_VALUES, "unknown")
    object_part = coerce_to_vocabulary(vision.get("object_part", ""), OBJECT_PART_VALUES, "unknown")
    severity = coerce_to_vocabulary(vision.get("severity", ""), SEVERITY_VALUES, "unknown")

    # `supporting_image_ids` are already 1-based (see contract.image_id). Anything the
    # model returned that is not a well-formed id is dropped rather than passed through.
    supporting = [
        s for s in (vision.get("supporting_image_ids") or [])
        if isinstance(s, str) and s.startswith("img_")
    ]

    # ── decision columns ──
    claim_status = coerce_to_vocabulary(
        decision.get("claim_status", ""), CLAIM_STATUS_VALUES, "not_enough_information"
    )
    justification = (
        decision.get("justification")
        or decision.get("summary")
        or "No automated verdict was produced for this claim."
    )

    return {
        "user_id": raw_claim.get("user_id", ""),
        "image_paths": raw_claim.get("image_paths", ""),
        "user_claim": raw_claim.get("user_claim", ""),
        "claim_object": raw_claim.get("claim_object", ""),
        "evidence_standard_met": to_bool_str(evidence_met),
        "evidence_standard_met_reason": evidence_reason,
        "risk_flags": join_multi(risk_flags, empty="none"),
        "issue_type": issue_type,
        "object_part": object_part,
        "claim_status": claim_status,
        "claim_status_justification": justification,
        "supporting_image_ids": join_multi(supporting, empty="none"),
        "valid_image": to_bool_str(valid_image),
        "severity": severity,
    }
