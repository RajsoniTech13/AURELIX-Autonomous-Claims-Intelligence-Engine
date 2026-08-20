"""
AURELIX v2 — FastAPI API Routes.

Maps the 7-agent graph state to database records and API responses.
"""
import os
import csv
import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
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
from platform_backend.services.uploads import read_documents, read_uploads

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
    if not evidence_rules_lookup:
        if os.path.exists(settings.EVIDENCE_REQUIREMENTS_CSV):
            with open(settings.EVIDENCE_REQUIREMENTS_CSV, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    evidence_rules_lookup[row["claim_object"].lower()] = row

@router.get("/")
def read_root():
    return {"message": "AURELIX Claims Intelligence API v2 is online"}

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
        query = query.filter(Claim.manual_review_required == escalated)
    return query.order_by(Claim.created_at.desc()).offset(offset).limit(limit).all()

@router.get("/claims/{claim_id}", response_model=ClaimDetailSchema)
def get_claim(claim_id: int, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


from platform_backend.services.claim_service import execute_claim_sync, generate_claim_stream

@router.post("/claims/submit", response_model=ClaimDetailSchema)
def submit_claim(claim_in: ClaimCreate, db: Session = Depends(get_db)):
    cached = get_cached_result(claim_in.user_id, claim_in.image_paths)
    if cached:
        db_claim = db.query(Claim).filter(
            Claim.user_id == claim_in.user_id,
            Claim.image_paths == claim_in.image_paths
        ).order_by(Claim.created_at.desc()).first()
        if db_claim:
            return db_claim

    load_lookups_if_empty()
    u_history = user_history_lookup.get(claim_in.user_id)
    e_rules = evidence_rules_lookup.get(claim_in.claim_object.lower())

    try:
        db_claim = execute_claim_sync(
            db=db,
            user_id=claim_in.user_id,
            image_paths=claim_in.image_paths,
            user_claim=claim_in.user_claim,
            claim_object=claim_in.claim_object,
            u_history=u_history,
            e_rules=e_rules
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent orchestrator failed: {str(e)}")

    try:
        set_cached_result(claim_in.user_id, claim_in.image_paths, {"id": db_claim.id})
    except Exception:
        pass

    return db_claim


@router.post("/claims/submit-multimodal", response_model=ClaimDetailSchema)
async def submit_claim_multimodal(
    user_id: str = Form(...),
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    files: List[UploadFile] = File([]),
    db: Session = Depends(get_db)
):
    pil_images, image_paths_str = await read_uploads(files)

    load_lookups_if_empty()
    u_history = user_history_lookup.get(user_id)
    e_rules = evidence_rules_lookup.get(claim_object.lower())

    try:
        db_claim = execute_claim_sync(
            db=db,
            user_id=user_id,
            image_paths=image_paths_str,
            user_claim=user_claim,
            claim_object=claim_object,
            u_history=u_history,
            e_rules=e_rules,
            pil_images=pil_images
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent orchestrator failed: {str(e)}")

    return db_claim


@router.post("/claims/submit-multimodal-stream")
async def submit_claim_multimodal_stream(
    user_id: str = Form(...),
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    files: List[UploadFile] = File([]),
    documents: List[UploadFile] = File([]),
    db: Session = Depends(get_db)
):
    from fastapi.responses import StreamingResponse

    pil_images, image_paths_str = await read_uploads(files)
    # Additive and optional: an existing client that posts no `documents` field
    # behaves exactly as before.
    doc_parts, document_paths_str = await read_documents(documents)

    load_lookups_if_empty()
    u_history = user_history_lookup.get(user_id)
    e_rules = evidence_rules_lookup.get(claim_object.lower())

    return StreamingResponse(
        generate_claim_stream(
            db=db,
            user_id=user_id,
            image_paths=image_paths_str,
            user_claim=user_claim,
            claim_object=claim_object,
            u_history=u_history,
            e_rules=e_rules,
            pil_images=pil_images,
            documents=doc_parts,
            document_paths=document_paths_str,
        ),
        media_type="text/event-stream"
    )



@router.get("/queue", response_model=List[ClaimSchema])
def list_manual_review_queue(db: Session = Depends(get_db)):
    return db.query(Claim).filter(
        Claim.manual_review_required == True,
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

    db_log = AuditLog(
        claim_id=claim.id,
        agent_name="Human Review (Manual Action)",
        inputs={"verdict": verdict_in.verdict, "notes": verdict_in.notes},
        outputs={"final_status": claim.claim_status},
        reasoning=f"Human reviewer set verdict to {verdict_in.verdict.upper()}. Notes: {verdict_in.notes}",
    )
    db.add(db_log)
    db.commit()
    db.refresh(claim)
    return claim


@router.get("/analytics", response_model=AnalyticsDashboardData)
def get_analytics(db: Session = Depends(get_db)):
    total = db.query(Claim).count()
    if total == 0:
        return AnalyticsDashboardData(
            kpis=KPIStats(total_claims=0, supported_claims=0, contradicted_claims=0, not_enough_info_claims=0, manual_review_claims=0,
                           pending_review_claims=0, average_confidence=0.0),
            status_distribution=[], object_distribution=[], severity_distribution=[],
            confidence_distribution=[], fraud_distribution=[], claims_over_time=[],
        )

    supported = db.query(Claim).filter(Claim.claim_status == "supported").count()
    contradicted = db.query(Claim).filter(Claim.claim_status == "contradicted").count()
    not_enough = db.query(Claim).filter(Claim.claim_status == "not_enough_information").count()
    escalated = db.query(Claim).filter(Claim.manual_review_required == True).count()
    # Same predicate as GET /queue, so the dashboard tile and the list it links to agree.
    pending_review = db.query(Claim).filter(
        Claim.manual_review_required == True,
        Claim.manual_verdict == None,  # noqa: E711 - SQLAlchemy needs `== None`, not `is None`
    ).count()
    avg_conf = db.query(func.avg(Claim.confidence_score)).scalar() or 0.0

    status_q = db.query(Claim.claim_status, func.count(Claim.id)).group_by(Claim.claim_status).all()
    status_dist = [StatusDistribution(status=r[0], count=r[1]) for r in status_q]

    object_q = db.query(Claim.claim_object, func.count(Claim.id)).group_by(Claim.claim_object).all()
    object_dist = [ObjectDistribution(object=r[0], count=r[1]) for r in object_q]

    severity_q = db.query(Claim.severity, func.count(Claim.id)).group_by(Claim.severity).all()
    severity_dist = [SeverityDistribution(severity=r[0], count=r[1]) for r in severity_q]

    conf_buckets = {
        "90-100": db.query(Claim).filter(Claim.confidence_score >= 90).count(),
        "70-89": db.query(Claim).filter(Claim.confidence_score >= 70, Claim.confidence_score < 90).count(),
        "<70": db.query(Claim).filter(Claim.confidence_score < 70).count(),
    }
    conf_dist = [ConfidenceBucket(bucket=k, count=v) for k, v in conf_buckets.items()]

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
            func.to_char(Claim.created_at, "YYYY-MM-DD"), func.count(Claim.id)
        ).group_by(func.to_char(Claim.created_at, "YYYY-MM-DD")).all()
    else:
        claims_date_q = db.query(
            func.strftime("%Y-%m-%d", Claim.created_at), func.count(Claim.id)
        ).group_by(func.strftime("%Y-%m-%d", Claim.created_at)).all()

    claims_over_time = [{"date": r[0], "claims": r[1]} for r in claims_date_q]

    return AnalyticsDashboardData(
        kpis=KPIStats(
            total_claims=total, supported_claims=supported, contradicted_claims=contradicted,
            not_enough_info_claims=not_enough, manual_review_claims=escalated,
            pending_review_claims=pending_review,
            average_confidence=round(float(avg_conf), 1),
        ),
        status_distribution=status_dist, object_distribution=object_dist,
        severity_distribution=severity_dist, confidence_distribution=conf_dist,
        fraud_distribution=fraud_dist, claims_over_time=claims_over_time,
    )
