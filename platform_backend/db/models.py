from sqlalchemy import Column, String, Integer, Boolean, DateTime, Float, Text, JSON, ForeignKey
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


class LLMCall(Base):
    """
    One model request — or one cache hit — and what it cost.

    Written by `services/llm_telemetry.py`, which subscribes to `agent_core.llm.telemetry`.
    Holds counts and labels only: **no prompt text, no answer, nothing a claimant wrote.**
    More people can read operational metrics than can read claims, so a metrics table must
    never become a second copy of claim content.

    A new table, deliberately, rather than columns on `claims`: `create_all` creates missing
    tables on an existing database but never adds columns to an existing table, so this
    deploys onto the live SQLite file without a migration.

    `claim_id` is filled in after the claim row exists (the model call happens before it
    does), by matching `request_id` — see `link_calls_to_claim`.
    """
    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=get_utc_now, index=True)

    task = Column(String(50), nullable=False, index=True)          # perception, copilot_answer
    provider = Column(String(30), nullable=False)                   # gemini, groq, cache, ...
    model = Column(String(80), nullable=False)
    prompt_version = Column(String(50), nullable=True)

    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    # List-price equivalent in USD; NULL when the model has no listed price. Billed cost on
    # the free tiers this project uses is $0 — see config/pricing.yaml.
    cost_usd = Column(Float, nullable=True)
    cache_hit = Column(Boolean, default=False)

    outcome = Column(String(30), nullable=False, index=True)        # ok, rate_limited, ...
    error_type = Column(String(80), nullable=True)

    request_id = Column(String(64), nullable=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True, index=True)


class User(Base):
    """
    An account. Three roles: `claimant` (submits claims, sees only their own), `reviewer`
    (sees every claim, decides escalated ones, uses the copilot), `admin` (everything).

    `password_hash` is Argon2id and is NULL for demo accounts, which cannot log in with a
    password at all — they exist only for the session the demo login created. No account,
    and no password, is ever committed to the repository: real accounts are seeded from the
    environment (`AURELIX_SEED_USERS`).

    `username` is what `claims.user_id` holds for a claim a claimant submitted, so ownership
    is a string comparison against a column that already existed — no migration of `claims`.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=get_utc_now)


class RefreshToken(Base):
    """
    One refresh token, stored only as a SHA-256 hash.

    Rotation: every refresh revokes the token used and issues a new one in the same
    `family_id`. **Reuse detection:** presenting a token that was already rotated means two
    parties hold it — the user and a thief — so the whole family is revoked and both must
    log in again. That is the standard defence for tokens that live in browser storage.
    """
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    family_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime, default=get_utc_now)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    replaced_by_id = Column(Integer, ForeignKey("refresh_tokens.id"), nullable=True)
