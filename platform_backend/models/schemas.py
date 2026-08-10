from pydantic import BaseModel, Field, field_serializer
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone


class UTCTimestamps(BaseModel):
    """
    Emit datetimes as unambiguous UTC.

    Every timestamp in this database is naive UTC (`datetime.now(timezone.utc)` with the
    tzinfo stripped, so SQLite stores something comparable). Serialised as-is that produces
    `2026-08-10T01:39:22`, and ECMAScript reads a date-time with no offset as **local
    time** — so a claim analysed a minute ago rendered hours in the future for anyone east
    of UTC, and every relative-time label in the UI was wrong by the reader's own offset.

    Appending the offset costs nothing and removes the guess.
    """

    @field_serializer("created_at", "updated_at", "timestamp", check_fields=False)
    def _as_utc(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.isoformat()


class ClaimBase(BaseModel):
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str

class ClaimCreate(ClaimBase):
    pass

class AuditLogSchema(UTCTimestamps):
    id: int
    agent_name: str
    timestamp: datetime
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    reasoning: Optional[str] = None

    class Config:
        from_attributes = True

class ClaimSchema(ClaimBase, UTCTimestamps):
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
