import io
import json
from PIL import Image
from sqlalchemy.orm import Session
from platform_backend.db.models import Claim, AuditLog
from platform_backend.services.cache import get_cached_result, set_cached_result
from agent_core import process_claim
from agent_core.orchestrator.graph import compiled_graph, _now

def _state_to_db_claim(state_res: dict, user_id: str, image_paths: str, user_claim: str, claim_object: str) -> Claim:
    """Map the 7-agent graph state to a Claim database row."""
    decision = state_res.get("decision", {})
    vision = state_res.get("vision", {})
    policy = state_res.get("policy", {})
    fraud = state_res.get("fraud", {})
    user_risk = state_res.get("user_risk", {})

    sup_imgs = vision.get("supporting_image_ids", [])
    sup_imgs_str = ";".join(sup_imgs) if sup_imgs else "none"

    risk_flags = user_risk.get("risk_flags", [])
    risk_flags_str = ";".join(risk_flags) if risk_flags else "none"

    return Claim(
        user_id=user_id,
        image_paths=image_paths,
        user_claim=user_claim,
        claim_object=claim_object,
        policy_status=policy.get("status", "PASS"),
        policy_reason=policy.get("reason", ""),
        issue_type=vision.get("issue_type", "unknown"),
        object_part=vision.get("object_part", "unknown"),
        severity=vision.get("severity", "unknown"),
        impact_direction=vision.get("impact_direction", "unknown"),
        drivable_status=vision.get("drivable_status", True),
        supporting_image_ids=sup_imgs_str,
        claim_status=decision.get("claim_status", "not_enough_information"),
        claim_status_justification=decision.get("justification", ""),
        confidence_score=decision.get("confidence", 0),
        manual_review_required=decision.get("manual_review_required", False),
        escalation_reason=decision.get("escalation_reason"),
        fraud_score=fraud.get("fraud_score", 0),
        user_risk_score=user_risk.get("risk_score", 0),
        risk_level=user_risk.get("risk_level", "LOW"),
        risk_flags=risk_flags_str,
    )

def _save_claim_and_audit(db: Session, db_claim: Claim, audit_logs: list):
    print("[DEBUG] Adding claim to DB...")
    db.add(db_claim)
    print("[DEBUG] Committing claim to DB...")
    db.commit()
    print("[DEBUG] Refreshing claim...")
    db.refresh(db_claim)

    print(f"[DEBUG] Adding {len(audit_logs)} audit logs...")
    for log in audit_logs:
        db_log = AuditLog(
            claim_id=db_claim.id,
            agent_name=log["agent_name"],
            inputs=log.get("inputs"),
            outputs=log.get("outputs"),
            reasoning=log.get("reasoning"),
        )
        db.add(db_log)
    print("[DEBUG] Committing audit logs...")
    db.commit()
    db.refresh(db_claim)
    return db_claim

def execute_claim_sync(
    db: Session, 
    user_id: str, 
    image_paths: str, 
    user_claim: str, 
    claim_object: str, 
    u_history: dict, 
    e_rules: dict, 
    pil_images: list = None
):
    state_res = process_claim(
        user_id=user_id,
        image_paths=image_paths,
        user_claim=user_claim,
        claim_object=claim_object,
        user_history=u_history,
        evidence_rules=e_rules,
        images=pil_images or [],
    )
    db_claim = _state_to_db_claim(state_res, user_id, image_paths, user_claim, claim_object)
    return _save_claim_and_audit(db, db_claim, state_res.get("audit_logs", []))

def generate_claim_stream(
    db: Session, 
    user_id: str, 
    image_paths: str, 
    user_claim: str, 
    claim_object: str, 
    u_history: dict, 
    e_rules: dict, 
    pil_images: list
):
    initial_state = {
        "user_id": user_id,
        "image_paths": image_paths,
        "user_claim": user_claim,
        "claim_object": claim_object,
        "user_history": u_history or {},
        "evidence_rules": e_rules or {},
        "images": pil_images or [],
        "image_base_dir": "",
        "image_validation": {}, "ingestion": {}, "vision": {}, "policy": {},
        "similar_claims": {}, "user_risk": {}, "fraud": {}, "decision": {},
        "audit_logs": [], "timeline": [], "pipeline_errors": [],
    }

    yield f'data: {json.dumps({"stage": "image_validator", "status": "running"})}\n\n'

    final_state = initial_state.copy()
    completed_branches = set()
    
    try:
        for event in compiled_graph.stream(initial_state):
            node_name = list(event.keys())[0]
            
            final_state.update(event[node_name])
            yield f'data: {json.dumps({"stage": node_name, "status": "complete", "timestamp": _now()})}\n\n'

            if node_name == "image_validator":
                # Ask the graph which way it will actually route rather than re-deriving
                # the condition here. The duplicated copy of this logic had already
                # drifted out of sync with the real router.
                from agent_core.orchestrator.graph import route_after_validation
                next_stage = route_after_validation(final_state)
                yield f'data: {json.dumps({"stage": next_stage, "status": "running"})}\n\n'
            
            elif node_name == "claim_ingestion":
                yield f'data: {json.dumps({"stage": "vision_analysis", "status": "running"})}\n\n'
                yield f'data: {json.dumps({"stage": "policy_verification", "status": "running"})}\n\n'
                yield f'data: {json.dumps({"stage": "similar_claims", "status": "running"})}\n\n'
                yield f'data: {json.dumps({"stage": "user_risk", "status": "running"})}\n\n'
            
            elif node_name in ["vision_analysis", "policy_verification", "similar_claims", "user_risk"]:
                completed_branches.add(node_name)
                if len(completed_branches) == 4:
                    yield f'data: {json.dumps({"stage": "fraud_review", "status": "running"})}\n\n'
            
            elif node_name == "fraud_review":
                yield f'data: {json.dumps({"stage": "decision", "status": "running"})}\n\n'

        print("[DEBUG] Graph stream finished successfully. Preparing DB save...")
        db_claim = _state_to_db_claim(final_state, user_id, image_paths, user_claim, claim_object)
        
        print("[DEBUG] Calling _save_claim_and_audit...")
        db_claim = _save_claim_and_audit(db, db_claim, final_state.get("audit_logs", []))
        print("[DEBUG] _save_claim_and_audit completed successfully!")
        
        claim_dict = {
            "id": db_claim.id, "user_id": db_claim.user_id, "image_paths": db_claim.image_paths,
            "user_claim": db_claim.user_claim, "claim_object": db_claim.claim_object,
            "claim_status": db_claim.claim_status, "claim_status_justification": db_claim.claim_status_justification,
            "confidence_score": db_claim.confidence_score, "manual_review_required": db_claim.manual_review_required,
            "escalation_reason": db_claim.escalation_reason, "policy_status": db_claim.policy_status,
            "policy_reason": db_claim.policy_reason, "issue_type": db_claim.issue_type,
            "object_part": db_claim.object_part, "severity": db_claim.severity,
            "impact_direction": db_claim.impact_direction, "drivable_status": db_claim.drivable_status,
            "fraud_score": db_claim.fraud_score, "user_risk_score": db_claim.user_risk_score,
            "risk_level": db_claim.risk_level, "risk_flags": db_claim.risk_flags,
            "created_at": db_claim.created_at.isoformat() if db_claim.created_at else None,
            "audit_logs": [{"agent_name": l.agent_name, "reasoning": l.reasoning, "timestamp": l.timestamp.isoformat()} for l in db_claim.audit_logs]
        }

        yield f'data: {json.dumps({"stage": "done", "claim": claim_dict})}\n\n'

    except Exception as e:
        print(f"[ERROR] execute_claim_sync generator failed: {str(e)}")
        yield f'data: {json.dumps({"error": str(e)})}\n\n'
