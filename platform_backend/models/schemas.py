from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class ClaimBase(BaseModel):
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str

class ClaimCreate(ClaimBase):
    pass

class AuditLogSchema(BaseModel):
    id: int
    agent_name: str
    timestamp: datetime
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    reasoning: Optional[str] = None

    class Config:
        from_attributes = True

class ClaimSchema(ClaimBase):
    id: int
    evidence_standard_met: bool
    evidence_standard_met_reason: Optional[str] = None
    risk_flags: Optional[str] = None
    issue_type: Optional[str] = None
    object_part: Optional[str] = None
    claim_status: str
    claim_status_justification: Optional[str] = None
    supporting_image_ids: Optional[str] = None
    valid_image: bool
    severity: str
    confidence_score: int
    fraud_score: int
    user_risk_score: int
    escalation_reason: Optional[str] = None
    manual_verdict: Optional[str] = None
    manual_reviewer_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ClaimDetailSchema(ClaimSchema):
    audit_logs: List[AuditLogSchema] = []

class ManualVerdictUpdate(BaseModel):
    verdict: str = Field(..., description="approved or rejected")
    notes: Optional[str] = None

# Analytics schemas
class KPIStats(BaseModel):
    total_claims: int
    supported_claims: int
    contradicted_claims: int
    not_enough_info_claims: int
    manual_review_claims: int
    average_confidence: float

class StatusDistribution(BaseModel):
    status: str
    count: int

class ObjectDistribution(BaseModel):
    object: str
    count: int

class SeverityDistribution(BaseModel):
    severity: str
    count: int

class ConfidenceBucket(BaseModel):
    bucket: str # "90-100", "70-89", "<70"
    count: int

class FraudBucket(BaseModel):
    bucket: str # "0-20", "21-50", "51-80", "81-100"
    count: int

class AnalyticsDashboardData(BaseModel):
    kpis: KPIStats
    status_distribution: List[StatusDistribution]
    object_distribution: List[ObjectDistribution]
    severity_distribution: List[SeverityDistribution]
    confidence_distribution: List[ConfidenceBucket]
    fraud_distribution: List[FraudBucket]
    claims_over_time: List[Dict[str, Any]]
