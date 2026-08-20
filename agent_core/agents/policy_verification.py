"""
Policy Verification Agent — DETERMINISTIC, no LLM call.

Reads evidence_requirements rules from CSV (never hardcoded).
Returns PASS / WARNING / FAIL with reason.
"""
import csv
import os
from typing import Dict, Any, List, Optional
from agent_core.agents.alignment import is_canonical_part, normalise_part
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
    #
    # Both sides go through the object-scoped ontology before being compared.
    #
    # They used to be compared as raw substrings, and the two sides never speak the
    # same dialect: the model reports what a person writes ("front bumper", "bonnet",
    # "windscreen") while the policy CSV is written in canonical form
    # ("front_bumper", "hood", "windshield"). Neither `"front_bumper" in "front bumper"`
    # nor the reverse is true, so **every naturally-worded part produced a WARNING** —
    # 20 of 34 claims in the live database, on claims that were otherwise perfectly
    # compliant.
    #
    # The second correction is about what this check is *for*. Policy visibility asks
    # "is the part the claimant named one this policy covers?" — a question about
    # coverage, which only has an answer once a part has been named. When the claimant
    # named nothing at all there is no visibility requirement to fail, and warning about
    # it duplicated R021, which already routes unspecified claims to review.
    #
    # A part that is named but unrecognised ("spoiler", "front_part") still warns: it is
    # not on the covered list, and that is exactly what a coverage check should say.
    allowed_parts_raw = policy.get("required_visibility", "")
    allowed_parts = [p.strip() for p in allowed_parts_raw.replace(",", ";").split(";") if p.strip()]

    canonical_claimed = normalise_part(claimed_part, claim_object)
    named_a_part = (claimed_part or "").strip().lower() not in ("", "unknown", "none", "unspecified")

    if allowed_parts and named_a_part:
        canonical_allowed = {normalise_part(p, claim_object) for p in allowed_parts}
        if canonical_claimed not in canonical_allowed:
            return PolicyVerificationOutput(
                status="WARNING",
                summary=f"'{claimed_part}' is outside the parts this policy covers.",
                reason=(
                    f"The claim names {canonical_claimed}, which is not among the parts "
                    f"covered for {claim_object} claims ({allowed_parts_raw}). The evidence "
                    f"itself meets requirements; the part may fall outside this policy."
                ),
                required_images=required_count,
                provided_images=provided_count,
                policy_active=True,
                rule_ids=[f"{rule_prefix}-VISIBILITY"],
            )

    # ── All checks passed ──
    covered = (
        f"Claimed part '{canonical_claimed}' is within visibility guidelines."
        if named_a_part
        else "No specific part was named, so no visibility requirement applies."
    )
    return PolicyVerificationOutput(
        status="PASS",
        summary=f"Evidence meets all policy requirements for {claim_object} claims.",
        reason=f"{provided_count} image(s) provided (minimum: {required_count}). {covered}",
        required_images=required_count,
        provided_images=provided_count,
        policy_active=True,
        rule_ids=[f"{rule_prefix}-COUNT", f"{rule_prefix}-VISIBILITY"],
    )
