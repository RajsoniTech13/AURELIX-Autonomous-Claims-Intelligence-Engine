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
    # Policy
    policy_status: Optional[str] = None
    policy_reason: Optional[str] = None
    # Vision
    issue_type: Optional[str] = None
    object_part: Optional[str] = None
    severity: str = "unknown"
    impact_direction: Optional[str] = None
    drivable_status: bool = True
    supporting_image_ids: Optional[str] = None
    # Decision
    claim_status: str
    claim_status_justification: Optional[str] = None
    confidence_score: int = 0
    manual_review_required: bool = False
    escalation_reason: Optional[str] = None
    # Fraud
    fraud_score: int = 0
    # User Risk
    user_risk_score: int = 0
    risk_level: Optional[str] = None
    risk_flags: Optional[str] = None
    # Manual Review
    manual_verdict: Optional[str] = None
    manual_reviewer_notes: Optional[str] = None
    # Meta
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
    bucket: str
    count: int

class FraudBucket(BaseModel):
    bucket: str
    count: int

class AnalyticsDashboardData(BaseModel):
    kpis: KPIStats
    status_distribution: List[StatusDistribution]
    object_distribution: List[ObjectDistribution]
    severity_distribution: List[SeverityDistribution]
    confidence_distribution: List[ConfidenceBucket]
    fraud_distribution: List[FraudBucket]
    claims_over_time: List[Dict[str, Any]]
