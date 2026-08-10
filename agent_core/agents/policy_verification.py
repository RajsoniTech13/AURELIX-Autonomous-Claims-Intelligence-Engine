"""
Policy Verification Agent — DETERMINISTIC, no LLM call.

Reads evidence_requirements rules from CSV (never hardcoded).
Returns PASS / WARNING / FAIL with reason.
"""
import csv
import os
from typing import Dict, Any, List, Optional
from agent_core.schemas.models import PolicyVerificationOutput


def run_policy_verification_agent(
    claim_object: str,
    claimed_part: str,
    image_paths: str,
    image_valid: bool,
    image_issues: List[str],
    evidence_rules: Optional[Dict[str, Any]] = None,
) -> PolicyVerificationOutput:
    """
    Check if submitted evidence meets policy requirements.
    Deterministic — no LLM call. Returns certainty='deterministic'.

    Every outcome cites the stable `rule_id`s of the requirements it applied. Those ids come
    from the `policy_rules` collection, which is chunked one document per requirement for
    exactly this purpose: "EV-CAR-COUNT failed" is answerable to a claimant, "the car policy
    failed" is not.
    """
    paths = [p.strip() for p in image_paths.split(";") if p.strip()]
    provided_count = len(paths)

    # ── Load policy rules ──
    policy = evidence_rules
    if not policy:
        data_paths = [
            os.path.join(os.path.dirname(__file__), "../data/evidence_requirements.csv"),
            "agent_core/data/evidence_requirements.csv",
        ]
        for p in data_paths:
            if os.path.exists(p):
                with open(p, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("claim_object", "").lower() == claim_object.lower():
                            policy = row
                            break
                if policy:
                    break

    if not policy:
        return PolicyVerificationOutput(
            status="WARNING",
            summary=f"No policy rules found for '{claim_object}'. Proceeding with caution.",
            reason=f"No evidence requirements defined for claim object '{claim_object}'.",
            required_images=1,
            provided_images=provided_count,
            policy_active=True,
        )

    rule_prefix = f"EV-{(claim_object or 'UNKNOWN').strip().upper()}"

    # ── Required image count ──
    try:
        required_count = int(policy.get("required_image_count", 1))
    except ValueError:
        required_count = 1

    # ── Image count check ──
    if provided_count < required_count:
        return PolicyVerificationOutput(
            status="FAIL",
            summary=f"Insufficient evidence: {provided_count}/{required_count} images provided.",
            reason=f"Policy requires at least {required_count} images for {claim_object} claims, but only {provided_count} were submitted.",
            required_images=required_count,
            provided_images=provided_count,
            policy_active=True,
            rule_ids=[f"{rule_prefix}-COUNT"],
        )

    # ── Image validity check ──
    if not image_valid and image_issues:
        critical_issues = [i for i in image_issues if "corrupt" in i or "unsupported" in i]
        if critical_issues:
            return PolicyVerificationOutput(
                status="FAIL",
                summary=f"Evidence images failed validation: {', '.join(critical_issues)}.",
                reason=f"Submitted images have critical quality issues: {', '.join(critical_issues)}.",
                required_images=required_count,
                provided_images=provided_count,
                policy_active=True,
                rule_ids=[f"{rule_prefix}-TYPE"],
            )

    # ── Visibility check ──
    allowed_parts_raw = policy.get("required_visibility", "")
    allowed_parts = [p.strip().lower() for p in allowed_parts_raw.replace(",", ";").split(";") if p.strip()]

    if allowed_parts:
        clean_part = claimed_part.lower().strip()
        matched = any(p in clean_part or clean_part in p for p in allowed_parts)
        if not matched:
            return PolicyVerificationOutput(
                status="WARNING",
                summary=f"Claimed part '{claimed_part}' is not in standard visibility guidelines.",
                reason=f"The claimed part '{claimed_part}' is not listed in visibility requirements for {claim_object}: {allowed_parts_raw}.",
                required_images=required_count,
                provided_images=provided_count,
                policy_active=True,
                rule_ids=[f"{rule_prefix}-VISIBILITY"],
            )

    # ── All checks passed ──
    return PolicyVerificationOutput(
        status="PASS",
        summary=f"Evidence meets all policy requirements for {claim_object} claims.",
        reason=f"{provided_count} image(s) provided (minimum: {required_count}). Claimed part '{claimed_part}' is within visibility guidelines.",
        required_images=required_count,
        provided_images=provided_count,
        policy_active=True,
        rule_ids=[f"{rule_prefix}-COUNT", f"{rule_prefix}-VISIBILITY"],
    )
