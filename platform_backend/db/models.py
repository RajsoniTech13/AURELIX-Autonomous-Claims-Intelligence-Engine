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
