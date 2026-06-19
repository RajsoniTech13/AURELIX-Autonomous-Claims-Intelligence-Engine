import os
import csv
import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile, Form
from PIL import Image
import io
from sqlalchemy.orm import Session
from sqlalchemy import func

from platform_backend.config import settings
from platform_backend.db.session import get_db
from platform_backend.db.models import Claim, AuditLog
from platform_backend.models.schemas import (
    ClaimSchema, ClaimCreate, ClaimDetailSchema, ManualVerdictUpdate,
    AnalyticsDashboardData, KPIStats, StatusDistribution,
    ObjectDistribution, SeverityDistribution, ConfidenceBucket, FraudBucket
)
from platform_backend.services.cache import get_cached_result, set_cached_result
from agent_core import process_claim

router = APIRouter()

# Lookup cache for lazy loading
user_history_lookup = {}
evidence_rules_lookup = {}

def load_lookups_if_empty():
    global user_history_lookup, evidence_rules_lookup
    if not user_history_lookup:
        if os.path.exists(settings.USER_HISTORY_CSV):
            with open(settings.USER_HISTORY_CSV, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    user_history_lookup[row["user_id"]] = row
        else:
            print(f"[API] Warning: user_history.csv not found at {settings.USER_HISTORY_CSV}")
            
    if not evidence_rules_lookup:
        if os.path.exists(settings.EVIDENCE_REQUIREMENTS_CSV):
            with open(settings.EVIDENCE_REQUIREMENTS_CSV, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    evidence_rules_lookup[row["claim_object"].lower()] = row
        else:
            print(f"[API] Warning: evidence_requirements.csv not found at {settings.EVIDENCE_REQUIREMENTS_CSV}")

@router.get("/")
def read_root():
    return {"message": "AURELIX Claims Intelligence API is online"}

@router.get("/claims", response_model=List[ClaimSchema])
def list_claims(
    status: Optional[str] = None,
    claim_object: Optional[str] = None,
    escalated: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    query = db.query(Claim)
    
    if status:
        query = query.filter(Claim.claim_status == status)
    if claim_object:
        query = query.filter(Claim.claim_object == claim_object)
    if escalated is not None:
        if escalated:
            query = query.filter(Claim.escalation_reason != None)
        else:
            query = query.filter(Claim.escalation_reason == None)
            
    return query.order_by(Claim.created_at.desc()).offset(offset).limit(limit).all()

@router.get("/claims/{claim_id}", response_model=ClaimDetailSchema)
def get_claim(claim_id: int, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim

@router.post("/claims/submit", response_model=ClaimDetailSchema)
def submit_claim(claim_in: ClaimCreate, db: Session = Depends(get_db)):
    # Check cache first
    cached = get_cached_result(claim_in.user_id, claim_in.image_paths)
    if cached:
        # Try to find in database to return detailed schema
        db_claim = db.query(Claim).filter(
            Claim.user_id == claim_in.user_id,
            Claim.image_paths == claim_in.image_paths
        ).order_by(Claim.created_at.desc()).first()
        if db_claim:
            print(f"[API] Cache Hit. Returning claim ID {db_claim.id} from cache and database.")
            return db_claim

    load_lookups_if_empty()
    u_history = user_history_lookup.get(claim_in.user_id)
    e_rules = evidence_rules_lookup.get(claim_in.claim_object.lower())

    # Run the orchestrator if cache misses
    try:
        state_res = process_claim(
            user_id=claim_in.user_id,
            image_paths=claim_in.image_paths,
            user_claim=claim_in.user_claim,
            claim_object=claim_in.claim_object,
            user_history=u_history,
            evidence_rules=e_rules
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent orchestrator execution failed: {str(e)}")
        
    # Extract results
    decision = state_res["decision"]
    vision = state_res["vision"]
    quality = state_res["quality"]
    compliance = state_res["compliance"]
    fraud = state_res["fraud"]
    user_risk = state_res["user_risk"]
    escalation = state_res["escalation"]
    
    q_flags = quality["quality_flags"]
    risk_flags = user_risk["risk_flags"]
    all_risk_flags = list(set(q_flags + risk_flags + (["manual_review_required"] if escalation["manual_review_required"] else [])))
    if "none" in all_risk_flags and len(all_risk_flags) > 1:
        all_risk_flags.remove("none")
    risk_flags_str = ";".join(all_risk_flags) if all_risk_flags else "none"
    
    sup_imgs = vision["supporting_image_ids"]
    sup_imgs_str = ";".join(sup_imgs) if sup_imgs else "none"
    
    # Save to database
    db_claim = Claim(
        user_id=claim_in.user_id,
        image_paths=claim_in.image_paths,
        user_claim=claim_in.user_claim,
        claim_object=claim_in.claim_object,
        evidence_standard_met=compliance["evidence_standard_met"],
        evidence_standard_met_reason=compliance["reason"],
        risk_flags=risk_flags_str,
        issue_type=vision["issue_type"],
        object_part=vision["object_part"],
        claim_status=decision["claim_status"],
        claim_status_justification=decision["justification"],
        supporting_image_ids=sup_imgs_str,
        valid_image=quality["image_valid"],
        severity=vision["severity"],
        confidence_score=state_res["confidence"]["confidence_score"],
        fraud_score=fraud["fraud_score"],
        user_risk_score=user_risk["user_risk_score"],
        escalation_reason=escalation["escalation_reason"] if escalation["manual_review_required"] else None
    )
    
    db.add(db_claim)
    db.commit()
    db.refresh(db_claim)
    
    # Store audit logs
    for log in state_res["audit_logs"]:
        db_log = AuditLog(
            claim_id=db_claim.id,
            agent_name=log["agent_name"],
            inputs=log.get("inputs"),
            outputs=log.get("outputs"),
            reasoning=log.get("reasoning")
        )
        db.add(db_log)
    db.commit()
    db.refresh(db_claim)
    
    # Save to cache
    try:
        claim_dict = {
            "id": db_claim.id,
            "user_id": db_claim.user_id,
            "image_paths": db_claim.image_paths,
            "user_claim": db_claim.user_claim,
            "claim_object": db_claim.claim_object,
            "claim_status": db_claim.claim_status,
            "severity": db_claim.severity,
            "confidence_score": db_claim.confidence_score,
            "fraud_score": db_claim.fraud_score
        }
        set_cached_result(claim_in.user_id, claim_in.image_paths, claim_dict)
    except Exception as e:
        print(f"Failed to cache result: {e}")
        
    return db_claim

@router.post("/claims/submit-multimodal", response_model=ClaimDetailSchema)
def submit_claim_multimodal(
    user_id: str = Form(...),
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    files: List[UploadFile] = File([]),
    db: Session = Depends(get_db)
):
    # Process files to PIL Images
    pil_images = []
    file_names = []
    
    for f in files:
        if not f.filename:
            continue
        try:
            content = f.file.read()
            img = Image.open(io.BytesIO(content))
            img.verify() # Verify it's a valid image
            # Reopen because verify() closes the file
            f.file.seek(0)
            img = Image.open(io.BytesIO(f.file.read()))
            pil_images.append(img)
            file_names.append(f.filename)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image file {f.filename}: {str(e)}")
            
    # Format them as image paths string (e.g. "images/img1.jpg;images/img2.jpg")
    image_paths_str = ";".join([f"images/{name}" for name in file_names]) if file_names else "none"
    
    load_lookups_if_empty()
    u_history = user_history_lookup.get(user_id)
    e_rules = evidence_rules_lookup.get(claim_object.lower())
    
    try:
        state_res = process_claim(
            user_id=user_id,
            image_paths=image_paths_str,
            user_claim=user_claim,
            claim_object=claim_object,
            user_history=u_history,
            evidence_rules=e_rules,
            images=pil_images
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent orchestrator execution failed: {str(e)}")
        
    # Extract results
    decision = state_res["decision"]
    vision = state_res["vision"]
    quality = state_res["quality"]
    compliance = state_res["compliance"]
    fraud = state_res["fraud"]
    user_risk = state_res["user_risk"]
    escalation = state_res["escalation"]
    
    q_flags = quality["quality_flags"]
    risk_flags = user_risk["risk_flags"]
    all_risk_flags = list(set(q_flags + risk_flags + (["manual_review_required"] if escalation["manual_review_required"] else [])))
    if "none" in all_risk_flags and len(all_risk_flags) > 1:
        all_risk_flags.remove("none")
    risk_flags_str = ";".join(all_risk_flags) if all_risk_flags else "none"
    
    sup_imgs = vision["supporting_image_ids"]
    sup_imgs_str = ";".join(sup_imgs) if sup_imgs else "none"
    
    # Save to database
    db_claim = Claim(
        user_id=user_id,
        image_paths=image_paths_str,
        user_claim=user_claim,
        claim_object=claim_object,
        evidence_standard_met=compliance["evidence_standard_met"],
        evidence_standard_met_reason=compliance["reason"],
        risk_flags=risk_flags_str,
        issue_type=vision["issue_type"],
        object_part=vision["object_part"],
        claim_status=decision["claim_status"],
        claim_status_justification=decision["justification"],
        supporting_image_ids=sup_imgs_str,
        valid_image=quality["image_valid"],
        severity=vision["severity"],
        confidence_score=state_res["confidence"]["confidence_score"],
        fraud_score=fraud["fraud_score"],
        user_risk_score=user_risk["user_risk_score"],
        escalation_reason=escalation["escalation_reason"] if escalation["manual_review_required"] else None
    )
    
    db.add(db_claim)
    db.commit()
    db.refresh(db_claim)
    
    # Store audit logs
    for log in state_res["audit_logs"]:
        db_log = AuditLog(
            claim_id=db_claim.id,
            agent_name=log["agent_name"],
            inputs=log.get("inputs"),
            outputs=log.get("outputs"),
            reasoning=log.get("reasoning")
        )
        db.add(db_log)
    db.commit()
    db.refresh(db_claim)
    
    return db_claim

@router.get("/queue", response_model=List[ClaimSchema])
def list_manual_review_queue(db: Session = Depends(get_db)):
    # Manual review items are those with an escalation reason and no manual verdict yet
    return db.query(Claim).filter(
        Claim.escalation_reason != None,
        Claim.manual_verdict == None
    ).order_by(Claim.created_at.desc()).all()

@router.post("/queue/{claim_id}/verdict", response_model=ClaimSchema)
def submit_manual_verdict(claim_id: int, verdict_in: ManualVerdictUpdate, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
        
    if verdict_in.verdict.lower() not in ["approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Verdict must be 'approved' or 'rejected'")
        
    claim.manual_verdict = verdict_in.verdict.lower()
    claim.manual_reviewer_notes = verdict_in.notes
    claim.claim_status = "supported" if verdict_in.verdict.lower() == "approved" else "contradicted"
    claim.updated_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    
    # Append a special manual action audit log
    db_log = AuditLog(
        claim_id=claim.id,
        agent_name="Human Review Agent (Action)",
        inputs={"verdict": verdict_in.verdict, "notes": verdict_in.notes},
        outputs={"final_status": claim.claim_status},
        reasoning=f"Human reviewer updated verdict to {verdict_in.verdict.upper()}. Notes: {verdict_in.notes}"
    )
    db.add(db_log)
    db.commit()
    db.refresh(claim)
    
    return claim

@router.get("/analytics", response_model=AnalyticsDashboardData)
def get_analytics(db: Session = Depends(get_db)):
    total = db.query(Claim).count()
    if total == 0:
        # Return empty shell
        return AnalyticsDashboardData(
            kpis=KPIStats(total_claims=0, supported_claims=0, contradicted_claims=0, not_enough_info_claims=0, manual_review_claims=0, average_confidence=0.0),
            status_distribution=[],
            object_distribution=[],
            severity_distribution=[],
            confidence_distribution=[],
            fraud_distribution=[],
            claims_over_time=[]
        )
        
    supported = db.query(Claim).filter(Claim.claim_status == "supported").count()
    contradicted = db.query(Claim).filter(Claim.claim_status == "contradicted").count()
    not_enough = db.query(Claim).filter(Claim.claim_status == "not_enough_information").count()
    escalated = db.query(Claim).filter(Claim.escalation_reason != None).count()
    
    avg_conf = db.query(func.avg(Claim.confidence_score)).scalar() or 0.0
    
    # Distributions
    status_q = db.query(Claim.claim_status, func.count(Claim.id)).group_by(Claim.claim_status).all()
    status_dist = [StatusDistribution(status=r[0], count=r[1]) for r in status_q]
    
    object_q = db.query(Claim.claim_object, func.count(Claim.id)).group_by(Claim.claim_object).all()
    object_dist = [ObjectDistribution(object=r[0], count=r[1]) for r in object_q]
    
    severity_q = db.query(Claim.severity, func.count(Claim.id)).group_by(Claim.severity).all()
    severity_dist = [SeverityDistribution(severity=r[0], count=r[1]) for r in severity_q]
    
    # Confidence buckets
    conf_buckets = {
        "90-100": db.query(Claim).filter(Claim.confidence_score >= 90).count(),
        "70-89": db.query(Claim).filter(Claim.confidence_score >= 70, Claim.confidence_score < 90).count(),
        "<70": db.query(Claim).filter(Claim.confidence_score < 70).count(),
    }
    conf_dist = [ConfidenceBucket(bucket=k, count=v) for k, v in conf_buckets.items()]
    
    # Fraud buckets
    fraud_buckets = {
        "0-20": db.query(Claim).filter(Claim.fraud_score <= 20).count(),
        "21-50": db.query(Claim).filter(Claim.fraud_score > 20, Claim.fraud_score <= 50).count(),
        "51-80": db.query(Claim).filter(Claim.fraud_score > 50, Claim.fraud_score <= 80).count(),
        "81-100": db.query(Claim).filter(Claim.fraud_score > 80).count(),
    }
    fraud_dist = [FraudBucket(bucket=k, count=v) for k, v in fraud_buckets.items()]
    
    # Claims over time
    if db.bind and db.bind.dialect.name == "postgresql":
        claims_date_q = db.query(
            func.to_char(Claim.created_at, "YYYY-MM-DD"), 
            func.count(Claim.id)
        ).group_by(func.to_char(Claim.created_at, "YYYY-MM-DD")).all()
    else:
        claims_date_q = db.query(
            func.strftime("%Y-%m-%d", Claim.created_at), 
            func.count(Claim.id)
        ).group_by(func.strftime("%Y-%m-%d", Claim.created_at)).all()
    
    claims_over_time = [{"date": r[0], "claims": r[1]} for r in claims_date_q]
    
    kpis = KPIStats(
        total_claims=total,
        supported_claims=supported,
        contradicted_claims=contradicted,
        not_enough_info_claims=not_enough,
        manual_review_claims=escalated,
        average_confidence=round(float(avg_conf), 1)
    )
    
    return AnalyticsDashboardData(
        kpis=kpis,
        status_distribution=status_dist,
        object_distribution=object_dist,
        severity_distribution=severity_dist,
        confidence_distribution=conf_dist,
        fraud_distribution=fraud_dist,
        claims_over_time=claims_over_time
    )
