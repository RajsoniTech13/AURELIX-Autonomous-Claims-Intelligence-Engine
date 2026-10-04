"""
AURELIX — the unversioned API routes the dashboard uses.

Every route that touches a claim declares who may call it (see `platform_backend/security.py`
for the full access table): claimants submit and read their own claims; reviewers and admins
read everything, work the review queue and see analytics. Only `/`, `/demo/status`,
`/health` and `/ready` are public.
"""
import os
import csv
import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from platform_backend.security import (
    current_principal, ensure_can_read, require_admin, require_reviewer, signed_assets, submitter_id,
)
from platform_backend.services import demo_guard
from platform_backend.services.auth import Principal
from platform_backend.services.rate_limit import enforce

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


def _visitor(request: Request) -> str:
    return demo_guard.visitor_key(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )


def _require_capacity(request: Request) -> None:
    """
    Refuse a live analysis that the shared free-tier budget cannot honestly fund.

    429 rather than 500: nothing is broken, the request is simply not being served now,
    and `Retry-After` tells the client when it will be. The payload carries the reason
    so the UI can explain the situation instead of showing a generic failure — the
    difference between a demo that looks rationed and one that looks dead.
    """
    decision = demo_guard.check(_visitor(request))
    if decision.allowed:
        return
    reset = demo_guard.next_reset()
    raise HTTPException(
        status_code=429,
        detail={"reason": decision.reason, "message": decision.detail,
                "resets_at": reset.isoformat()},
        headers={"Retry-After": str(max(1, int((reset - datetime.datetime.now(
            datetime.timezone.utc)).total_seconds())))},
    )


@router.get("/demo/status", tags=["ops"])
def demo_status(request: Request):
    """
    What the front end needs to set expectations before a visitor fills in a form.

    Asked on load, so that a visitor learns the day's budget is spent *before* writing
    a claim statement and uploading photographs, rather than after.
    """
    return demo_guard.status(_visitor(request))

def _asset_paths(claim: Claim) -> List[str]:
    """Photographs from the claim row; documents from the document_check audit record."""
    paths = [p for p in (claim.image_paths or "").split(";") if p and p != "none"]
    for log in claim.audit_logs:
        if log.agent_name == "document_check":
            paths.extend((log.inputs or {}).get("document_paths") or [])
    return paths


def claim_detail(claim: Claim) -> Dict[str, Any]:
    """The claim as the case file needs it, with signed URLs for its evidence."""
    body = ClaimDetailSchema.model_validate(claim).model_dump(mode="json")
    body["asset_urls"] = signed_assets(_asset_paths(claim))
    return body


def _submission_checks(request: Request, principal: Principal) -> str:
    """Rate limit and demo capacity, checked before any upload is read or stored."""
    enforce(f"submit:{principal.user_id}", "claim_submissions_per_hour", 3600, "claim submissions")
    _require_capacity(request)
    return _visitor(request)


@router.get("/claims", response_model=List[ClaimSchema])
def list_claims(
    status: Optional[str] = None,
    claim_object: Optional[str] = None,
    escalated: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    query = db.query(Claim)
    if not principal.is_reviewer:
        query = query.filter(Claim.user_id == principal.username)
    if status:
        query = query.filter(Claim.claim_status == status)
    if claim_object:
        query = query.filter(Claim.claim_object == claim_object)
    if escalated is not None:
        query = query.filter(Claim.manual_review_required == escalated)
    limit = max(1, min(limit, 200))
    return query.order_by(Claim.created_at.desc()).offset(max(0, offset)).limit(limit).all()


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, db: Session = Depends(get_db),
              principal: Principal = Depends(current_principal)):
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    ensure_can_read(principal, claim.user_id)
    return claim_detail(claim)


from platform_backend.services.claim_service import execute_claim_sync, generate_claim_stream

@router.post("/claims/submit", response_model=ClaimDetailSchema)
def submit_claim(claim_in: ClaimCreate, db: Session = Depends(get_db),
                 principal: Principal = Depends(require_admin)):
    """
    Legacy JSON submission with server-side `image_paths`. **Admin only:** the paths are
    resolved on the server's own disk, so letting any caller name them would let a caller
    probe which image files exist on the host. The dashboard never uses this route.
    """
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


@router.post("/claims/submit-multimodal")
async def submit_claim_multimodal(
    request: Request,
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    user_id: Optional[str] = Form(None),
    files: List[UploadFile] = File([]),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    visitor = _submission_checks(request, principal)
    pil_images, image_paths_str = await read_uploads(files)
    # Counted only once the uploads are accepted: a rejected file must not use up one of
    # the visitor's analyses. (This route used to check the cap and never count at all.)
    demo_guard.consume(visitor)
    owner = submitter_id(principal, user_id)

    load_lookups_if_empty()
    u_history = user_history_lookup.get(owner)
    e_rules = evidence_rules_lookup.get(claim_object.lower())

    try:
        db_claim = execute_claim_sync(
            db=db,
            user_id=owner,
            image_paths=image_paths_str,
            user_claim=user_claim,
            claim_object=claim_object,
            u_history=u_history,
            e_rules=e_rules,
            pil_images=pil_images
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent orchestrator failed: {str(e)}")

    return claim_detail(db_claim)


@router.post("/claims/submit-multimodal-stream")
async def submit_claim_multimodal_stream(
    request: Request,
    user_claim: str = Form(...),
    claim_object: str = Form(...),
    user_id: Optional[str] = Form(None),
    files: List[UploadFile] = File([]),
    documents: List[UploadFile] = File([]),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    from fastapi.responses import StreamingResponse

    # Before the uploads are read, so a refused request costs no disk and no decode.
    visitor = _submission_checks(request, principal)

    pil_images, image_paths_str = await read_uploads(files)
    # Additive and optional: an existing client that posts no `documents` field
    # behaves exactly as before.
    doc_parts, document_paths_str = await read_documents(documents)
    # Counted after the uploads are accepted. It used to be counted first, so a rejected
    # upload still used up one of a visitor's analyses.
    demo_guard.consume(visitor)
    owner = submitter_id(principal, user_id)

    load_lookups_if_empty()
    u_history = user_history_lookup.get(owner)
    e_rules = evidence_rules_lookup.get(claim_object.lower())

    return StreamingResponse(
        generate_claim_stream(
            db=db,
            user_id=owner,
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
def list_manual_review_queue(db: Session = Depends(get_db),
                             principal: Principal = Depends(require_reviewer)):
    return db.query(Claim).filter(
        Claim.manual_review_required == True,
        Claim.manual_verdict == None
    ).order_by(Claim.created_at.desc()).all()


@router.post("/queue/{claim_id}/verdict", response_model=ClaimSchema)
def submit_manual_verdict(claim_id: int, verdict_in: ManualVerdictUpdate, db: Session = Depends(get_db),
                          principal: Principal = Depends(require_reviewer)):
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
        # Who decided is part of the decision: the audit trail names the reviewer account.
        inputs={"verdict": verdict_in.verdict, "notes": verdict_in.notes,
                "reviewer": principal.username},
        outputs={"final_status": claim.claim_status},
        reasoning=f"Reviewer {principal.username} set verdict to {verdict_in.verdict.upper()}. Notes: {verdict_in.notes}",
    )
    db.add(db_log)
    db.commit()
    db.refresh(claim)
    return claim


@router.get("/analytics", response_model=AnalyticsDashboardData)
def get_analytics(db: Session = Depends(get_db), principal: Principal = Depends(require_reviewer)):
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
