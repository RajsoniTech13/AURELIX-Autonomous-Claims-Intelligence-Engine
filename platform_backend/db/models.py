from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

Base = declarative_base()

class Claim(Base):
    __tablename__ = "claims"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    image_paths = Column(Text, nullable=True)  # Semicolon separated
    user_claim = Column(Text, nullable=False)
    claim_object = Column(String(50), nullable=False)
    
    # Policy Verification
    policy_status = Column(String(20), default="PASS")  # PASS, WARNING, FAIL
    policy_reason = Column(Text, nullable=True)
    
    # Vision Analysis
    issue_type = Column(String(50), nullable=True)
    object_part = Column(String(100), nullable=True)
    severity = Column(String(20), default="unknown")  # none, minor, moderate, severe
    impact_direction = Column(String(20), nullable=True)  # front, rear, left, right, top, unknown
    drivable_status = Column(Boolean, default=True)
    supporting_image_ids = Column(String(255), nullable=True)
    
    # Decision (absorbs Confidence + Human Review)
    claim_status = Column(String(50), default="under_review")  # supported, contradicted, not_enough_information
    claim_status_justification = Column(Text, nullable=True)
    confidence_score = Column(Integer, default=0)
    manual_review_required = Column(Boolean, default=False)
    escalation_reason = Column(Text, nullable=True)
    
    # Fraud
    fraud_score = Column(Integer, default=0)
    
    # User Risk
    user_risk_score = Column(Integer, default=0)
    risk_level = Column(String(10), nullable=True)  # LOW, MEDIUM, HIGH
    risk_flags = Column(Text, nullable=True)  # Semicolon separated
    
    # Manual Review Override
    manual_verdict = Column(String(50), nullable=True)  # approved, rejected (by human)
    manual_reviewer_notes = Column(Text, nullable=True)
    
    # Meta
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    
    # Relationships
    audit_logs = relationship("AuditLog", back_populates="claim", cascade="all, delete-orphan")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    timestamp = Column(DateTime, default=get_utc_now)
    
    # Agent Execution Details
    agent_name = Column(String(100), nullable=False)
    inputs = Column(JSON, nullable=True)
    outputs = Column(JSON, nullable=True)
    reasoning = Column(Text, nullable=True)
    
    claim = relationship("Claim", back_populates="audit_logs")


class Job(Base):
    """
    One submitted claim's analysis, tracked as a job rather than a blocked HTTP request.

    Analysing a claim takes as long as the model takes — measured at ~14 seconds. Holding a
    worker open for that means concurrency is bounded by worker count, a slow model becomes
    a site outage, and any client timeout loses work that has already been paid for out of a
    20-request daily budget. So submission returns 202 with a job id, and the result is
    collected by polling or by an event stream.

    The job row is also the progress channel: the runner writes each pipeline stage here as
    it completes, and the SSE endpoint reads it. That is deliberately boring — no broker, no
    pub/sub — because the state has to survive a client reconnecting anyway, which means it
    has to be durable, which means the database is already the right place for it.
    """
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, index=True)          # uuid4
    user_id = Column(String(50), nullable=False, index=True)

    # queued -> running -> succeeded | failed
    status = Column(String(20), nullable=False, default="queued", index=True)
    stage = Column(String(50), nullable=True)                      # last completed stage
    progress = Column(JSON, nullable=True)                         # [{stage, status, at}]

    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    error = Column(Text, nullable=True)

    # Idempotency-Key, scoped per user. A retried submission must not spend a second
    # request out of the daily budget, and must not create a second claim record.
    idempotency_key = Column(String(255), nullable=True, index=True)

    submitted_payload = Column(JSON, nullable=True)                # what was asked for
    created_at = Column(DateTime, default=get_utc_now, index=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    claim = relationship("Claim")
