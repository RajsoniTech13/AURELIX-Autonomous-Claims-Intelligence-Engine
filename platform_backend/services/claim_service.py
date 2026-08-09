"""
Claim execution for the web platform.

This module used to drive `agent_core.orchestrator.graph` — ten nodes, four LLM calls per
claim, and a fraud/decision verdict produced by the model. That pipeline was superseded in
Phase 2/4 and the platform was never moved across, so every accuracy improvement of the
last three phases stopped at the CLI and never reached a user.

It now calls `agent_core.service.analyse_claim_events`, the same code path the benchmark
runs: one multimodal request per claim, then deterministic alignment, fraud scoring,
confidence and rules. There is no fallback to the old flow — `agent_core` no longer exports
it, and `tests/test_backend_pipeline.py` asserts that this module cannot reach it.

**Progress events come from `agent_core`, not from here.** The previous version kept its own
copy of the graph's routing logic to drive the SSE stream, and that copy had already drifted
out of sync with the real router. The generator now forwards what the pipeline actually
reports.
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

from agent_core.service import ClaimAnalysis, analyse_claim_events
from platform_backend.db.models import AuditLog, Claim


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _analysis_to_db_claim(
    analysis: ClaimAnalysis,
    user_id: str,
    image_paths: str,
    user_claim: str,
    claim_object: str,
) -> Claim:
    """
    Map one `ClaimAnalysis` onto a `Claim` row.

    Field-level notes, because two columns changed meaning and one lost its source:

    * `policy_status` / `policy_reason` still come from the deterministic policy agent,
      which was never an LLM call and survives the migration unchanged.
    * `user_risk_score` / `risk_level` likewise, from the deterministic user-history agent.
    * `issue_type` / `object_part` / `severity` now come from the frozen output contract
      row rather than raw model prose, so they are guaranteed to be inside the grader's
      vocabulary before they reach the database.
    * `impact_direction` and `drivable_status` have **no source in the new pipeline**. They
      were free-text fields on the old vision agent's response and are not part of the
      structured perception schema. Columns are retained and left at their defaults so no
      migration is required and no consumer breaks; see docs/PHASE_4.2_REPORT.md.
    """
    verdict = analysis.verdict
    row = analysis.output_row
    policy = analysis.policy
    risk = analysis.user_risk

    supporting = row.get("supporting_image_ids") or "none"
    risk_flags = ";".join(verdict.risk_flags) if verdict.risk_flags else "none"

    return Claim(
        user_id=user_id,
        image_paths=image_paths,
        user_claim=user_claim,
        claim_object=claim_object,
        policy_status=getattr(policy, "status", "PASS"),
        policy_reason=getattr(policy, "reason", ""),
        issue_type=row.get("issue_type", "unknown"),
        object_part=row.get("object_part", "unknown"),
        severity=row.get("severity", "unknown"),
        impact_direction=None,
        drivable_status=True,
        supporting_image_ids=supporting,
        claim_status=verdict.claim_status,
        claim_status_justification=verdict.justification,
        confidence_score=verdict.confidence,
        manual_review_required=verdict.manual_review_required,
        escalation_reason=verdict.escalation_reason,
        fraud_score=verdict.fraud_score,
        user_risk_score=getattr(risk, "risk_score", 0),
        risk_level=getattr(risk, "risk_level", "LOW"),
        risk_flags=risk_flags,
    )


def _audit_logs_for(analysis: ClaimAnalysis) -> List[Dict[str, Any]]:
    """
    Build the per-stage audit trail.

    An insurance product without an audit trail is not shippable, and the trail is more
    useful now than it was: every deterministic stage can state exactly which rule fired,
    and the perception stage records what the model claimed to see *alongside* what the
    preflight gate measured, so a reviewer can see where the two disagreed.
    """
    logs: List[Dict[str, Any]] = []

    quality = analysis.preflight_quality
    logs.append({
        "agent_name": "preflight",
        "inputs": {"images_declared": getattr(analysis.validation, "file_count", 0)},
        "outputs": quality.to_dict() if quality else None,
        "reasoning": (
            f"Measured image quality {quality.overall} deterministically "
            f"(blur/exposure, no model involved)." if quality and quality.measured
            else "No image could be measured."
        ),
    })

    if analysis.perception:
        p = analysis.perception
        logs.append({
            "agent_name": "perception",
            "inputs": {"claim_object": p.claim_understanding.object_category},
            "outputs": p.model_dump(),
            "reasoning": (
                f"Single multimodal request. Observed {p.observed_object}; "
                f"model self-rated quality {p.image_quality.overall}; "
                f"{len(p.damage_analysis.damaged_parts)} damaged part(s) reported."
            ),
        })
    else:
        logs.append({
            "agent_name": "perception",
            "inputs": {}, "outputs": {"error": analysis.error},
            "reasoning": (
                f"No perception was produced ({analysis.error}). No verdict was inferred "
                f"from claim text alone."
            ),
        })

    if analysis.policy is not None:
        logs.append({
            "agent_name": "policy_verification",
            "inputs": {}, "outputs": analysis.policy.model_dump(),
            "reasoning": analysis.policy.reason,
        })
    if analysis.user_risk is not None:
        logs.append({
            "agent_name": "user_risk",
            "inputs": {}, "outputs": analysis.user_risk.model_dump(),
            "reasoning": analysis.user_risk.summary,
        })
    if analysis.alignment is not None:
        logs.append({
            "agent_name": "alignment",
            "inputs": {}, "outputs": analysis.alignment.to_dict(),
            "reasoning": " ".join(analysis.alignment.notes) or
                         f"part_match={analysis.alignment.part_match}, "
                         f"severity_delta={analysis.alignment.severity_delta}",
        })

    logs.append({
        "agent_name": "decision",
        "inputs": {}, "outputs": analysis.verdict.to_dict(),
        "reasoning": analysis.verdict.justification,
    })
    return logs


def _save_claim_and_audit(db: Session, db_claim: Claim, audit_logs: List[Dict[str, Any]]) -> Claim:
    db.add(db_claim)
    db.commit()
    db.refresh(db_claim)

    for log in audit_logs:
        db.add(AuditLog(
            claim_id=db_claim.id,
            agent_name=log["agent_name"],
            inputs=log.get("inputs"),
            outputs=log.get("outputs"),
            reasoning=log.get("reasoning"),
        ))
    db.commit()
    db.refresh(db_claim)
    return db_claim


def _claim_to_dict(db_claim: Claim) -> Dict[str, Any]:
    return {
        "id": db_claim.id, "user_id": db_claim.user_id, "image_paths": db_claim.image_paths,
        "user_claim": db_claim.user_claim, "claim_object": db_claim.claim_object,
        "claim_status": db_claim.claim_status,
        "claim_status_justification": db_claim.claim_status_justification,
        "confidence_score": db_claim.confidence_score,
        "manual_review_required": db_claim.manual_review_required,
        "escalation_reason": db_claim.escalation_reason,
        "policy_status": db_claim.policy_status, "policy_reason": db_claim.policy_reason,
        "issue_type": db_claim.issue_type, "object_part": db_claim.object_part,
        "severity": db_claim.severity, "impact_direction": db_claim.impact_direction,
        "drivable_status": db_claim.drivable_status,
        "fraud_score": db_claim.fraud_score, "user_risk_score": db_claim.user_risk_score,
        "risk_level": db_claim.risk_level, "risk_flags": db_claim.risk_flags,
        "created_at": db_claim.created_at.isoformat() if db_claim.created_at else None,
        "audit_logs": [
            {"agent_name": l.agent_name, "reasoning": l.reasoning,
             "timestamp": l.timestamp.isoformat()}
            for l in db_claim.audit_logs
        ],
    }


def execute_claim_sync(
    db: Session,
    user_id: str,
    image_paths: str,
    user_claim: str,
    claim_object: str,
    u_history: Optional[dict],
    e_rules: Optional[dict],
    pil_images: Optional[list] = None,
    image_base_dir: Optional[str] = None,
) -> Claim:
    """Analyse one claim and persist it. Signature unchanged from the pre-migration version."""
    analysis: Optional[ClaimAnalysis] = None
    for event in analyse_claim_events(
        user_id=user_id, user_claim=user_claim, claim_object=claim_object,
        image_paths=image_paths, images=pil_images or None,
        image_base_dir=image_base_dir, user_history=u_history, evidence_rules=e_rules,
    ):
        if event["stage"] == "done":
            analysis = event["analysis"]

    assert analysis is not None
    db_claim = _analysis_to_db_claim(analysis, user_id, image_paths, user_claim, claim_object)
    return _save_claim_and_audit(db, db_claim, _audit_logs_for(analysis))


def generate_claim_stream(
    db: Session,
    user_id: str,
    image_paths: str,
    user_claim: str,
    claim_object: str,
    u_history: Optional[dict],
    e_rules: Optional[dict],
    pil_images: Optional[list] = None,
    image_base_dir: Optional[str] = None,
) -> Iterator[str]:
    """
    Server-sent events: one `{stage, status}` per pipeline stage, then `{stage: "done"}`.

    The event shape is unchanged, so the existing client contract holds. The *stage names*
    changed, because the stages themselves did — see docs/PHASE_4.2_REPORT.md.
    """
    analysis: Optional[ClaimAnalysis] = None
    try:
        for event in analyse_claim_events(
            user_id=user_id, user_claim=user_claim, claim_object=claim_object,
            image_paths=image_paths, images=pil_images or None,
            image_base_dir=image_base_dir, user_history=u_history, evidence_rules=e_rules,
        ):
            if event["stage"] == "done":
                analysis = event["analysis"]
                continue
            yield f'data: {json.dumps({**event, "timestamp": _now()})}\n\n'

        assert analysis is not None
        db_claim = _analysis_to_db_claim(
            analysis, user_id, image_paths, user_claim, claim_object,
        )
        db_claim = _save_claim_and_audit(db, db_claim, _audit_logs_for(analysis))
        yield f'data: {json.dumps({"stage": "done", "claim": _claim_to_dict(db_claim)})}\n\n'

    except Exception as e:  # noqa: BLE001 - the stream must report, not crash the response
        yield f'data: {json.dumps({"error": f"{type(e).__name__}: {e}"})}\n\n'
