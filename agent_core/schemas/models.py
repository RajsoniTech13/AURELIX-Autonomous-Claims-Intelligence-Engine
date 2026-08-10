"""
AURELIX v2 — Pydantic v2 schemas for every agent I/O contract and the LangGraph state.

Design rules:
- Every LLM agent output includes: status, summary, confidence (0-100).
- Every deterministic agent output includes: status, summary, certainty="deterministic".
  (Avoids a fake confidence:100 that looks dishonest next to real LLM-computed scores.)
- ClaimsState is the single TypedDict passed through the entire LangGraph DAG.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Annotated
from operator import add
from pydantic import BaseModel, Field

from agent_core.schemas.contract import ClaimStatus, IssueType, Severity


# ─── Utility: Image Validator (not an agent, no LLM call) ───────────────────

class ImageValidatorOutput(BaseModel):
    """
    Deterministic pre-flight check on submitted images.

    `valid` means "at least one image is genuinely usable for damage assessment". It is
    NOT satisfied by a path string alone — a declared path that does not resolve to a
    readable image is a failure, not a fallback.
    """
    valid: bool = Field(..., description="Is at least one image usable for downstream analysis?")
    file_count: int = Field(..., description="Number of image files declared by the claim")
    accepted_files: List[str] = Field(default_factory=list, description="1-based image ids that passed validation, e.g. ['img_1']")
    issues: List[str] = Field(default_factory=list, description="Raw diagnostic issues, e.g. missing_file:img_1, too_low_resolution:img_2:64x64")
    risk_flags: List[str] = Field(default_factory=list, description="Issues mapped into the frozen risk_flags vocabulary")
    images_supplied: bool = Field(False, description="Were decoded image objects actually supplied, as opposed to paths only?")


# ─── Agent 1: Claim Ingestion (Gemini, text-only) ───────────────────────────

class ClaimIngestionOutput(BaseModel):
    """Parses claim text into structured fields. Never analyzes images."""
    status: str = Field(..., description="'success' or 'error'")
    summary: str = Field(..., description="1-2 sentence summary of the claim")
    confidence: int = Field(..., description="Agent self-assessed confidence 0-100")
    claim_type: str = Field(..., description="vehicle_damage, electronics_damage, or package_damage")
    incident_summary: str = Field(..., description="What happened, in the claimant's own words")
    object: str = Field(..., description="car, laptop, or package")
    claimed_part: str = Field(..., description="Specific part claimed damaged, e.g. front_bumper, screen")
    claimed_issue: str = Field(..., description="Type of damage claimed, e.g. crack, dent, scratch")


# ─── Agent 2: Vision Analysis (Gemini Vision — the expensive call) ──────────

class VisionAnalysisOutput(BaseModel):
    """
    Detects damage from images. Never assesses fraud. Never estimates repair cost.

    Vocabulary is enforced by `Literal` -> Gemini `response_schema` enum, not by prompt
    text. `unknown` is a first-class value: it means "the evidence does not let me tell",
    which is distinct from `none` ("I looked and there is no damage"). Downstream, that
    distinction is what separates not_enough_information from contradicted.
    """
    status: str = Field(..., description="'success' or 'error'")
    summary: str = Field(..., description="Brief natural-language summary of what was found")
    confidence: int = Field(..., ge=0, le=100, description="Agent self-assessed confidence 0-100")
    damage_detected: bool = Field(..., description="Is physical damage visible?")
    object_part: str = Field(..., description="Part where damage is visible, or 'none'/'unknown'")
    issue_type: IssueType = Field(..., description="Type of damage observed. Use 'unknown' if the evidence does not let you tell.")
    severity: Severity = Field(..., description="Damage severity. Use 'unknown' if the evidence does not let you tell; 'none' only if you can see there is no damage.")
    impact_direction: Literal["front", "rear", "left", "right", "top", "unknown"] = Field(..., description="Direction of impact")
    drivable_status: bool = Field(True, description="Is the vehicle/object still functional?")
    claimed_part_visible: bool = Field(True, description="Is the part named in the claim actually visible in at least one image? False means we cannot confirm or deny damage to it.")
    supporting_image_ids: List[str] = Field(default_factory=list, description="1-based ids of images that show the damage, e.g. ['img_1', 'img_2']")
    justification: str = Field(..., description="Reasoning grounded in what the evidence actually shows")


# ─── Agent 3: Policy Verification (DETERMINISTIC, no LLM call) ──────────────

class PolicyVerificationOutput(BaseModel):
    """Checks evidence against policy rules loaded from the database. Never hardcoded."""
    status: str = Field(..., description="PASS, WARNING, or FAIL")
    summary: str = Field(..., description="Human-readable summary of the policy check")
    certainty: str = Field(default="deterministic", description="Always 'deterministic' for rule-based agents")
    reason: str = Field(..., description="Detailed explanation of why the status was assigned")
    required_images: int = Field(..., description="Minimum images required by policy")
    provided_images: int = Field(..., description="Actual images provided by claimant")
    policy_active: bool = Field(True, description="Is the claimant's policy currently active?")
    rule_ids: List[str] = Field(
        default_factory=list,
        description="Stable ids of the evidence requirements this check applied, e.g. "
                    "['EV-CAR-COUNT']. Retrieved from the policy_rules collection rather "
                    "than hardcoded, so a compliance failure names the requirement it "
                    "failed instead of gesturing at a whole policy.",
    )


# ─── Agent 4: Similar Claims (DETERMINISTIC TF-IDF retrieval) ───────────────

class SimilarClaimMatch(BaseModel):
    """A single matched historical claim."""
    claim_id: str = Field(..., description="User ID or claim identifier from historical data")
    similarity: float = Field(..., description="Cosine similarity score 0.0-1.0")
    claim_object: str = Field(..., description="Object type of the historical claim")
    issue_type: str = Field(..., description="Damage type of the historical claim")
    claim_status: str = Field(..., description="Resolution of the historical claim")
    repair_range: str = Field(default="unknown", description="Typical repair cost range, e.g. '$500-$1200'")
    settlement_duration_days: int = Field(default=0, description="Days to settle the historical claim")


class SimilarClaimsOutput(BaseModel):
    """TF-IDF cosine similarity retrieval over historical claims. No LLM call."""
    status: str = Field(..., description="'success' or 'no_matches'")
    summary: str = Field(..., description="Natural-language synthesis of how similar claims were resolved")
    certainty: str = Field(default="deterministic", description="Always 'deterministic' for retrieval agents")
    similar_claims: List[SimilarClaimMatch] = Field(default_factory=list)


# ─── Agent 5: User Risk (DETERMINISTIC, database-only) ─────────────────────

class UserRiskOutput(BaseModel):
    """Reads user_history table only. Never overrides visual evidence."""
    status: str = Field(..., description="'success' or 'no_history'")
    summary: str = Field(..., description="1-2 sentence risk profile explanation")
    certainty: str = Field(default="deterministic", description="Always 'deterministic' for rule-based agents")
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(..., description="Overall risk band")
    risk_score: int = Field(..., ge=0, le=100, description="Numeric risk score 0-100")
    risk_flags: List[str] = Field(default_factory=list, description="Flags in the frozen output vocabulary, e.g. ['user_history_risk']")
    detail_flags: List[str] = Field(default_factory=list, description="Human-readable specifics behind risk_flags, e.g. ['high_rejection_rate']. Never written to output.csv.")


# ─── Agent 6: Fraud Review (Gemini, conservative reasoning) ─────────────────

class FraudReviewOutput(BaseModel):
    """
    Gemini-powered fraud assessment over aggregated JSON from all prior agents.
    Fraud is NEVER assumed. Requires objective evidence. If none exists, score=5-15.
    """
    status: str = Field(..., description="'success' or 'error'")
    summary: str = Field(..., description="Brief conclusion of fraud assessment")
    confidence: int = Field(..., description="Agent self-assessed confidence 0-100")
    fraud_score: int = Field(..., description="Fraud risk score 0-100. Must be 5-15 if no objective evidence.")
    fraud_flags: List[str] = Field(default_factory=list, description="e.g. duplicate_evidence, metadata_mismatch, expired_policy, contradictory_documents, duplicate_vin, reused_image")
    reasoning: str = Field(..., description="Detailed explanation grounding every flag in objective evidence")


# ─── Agent 7: Decision (Gemini, final call — absorbs Confidence + Human Review) ─

class DecisionOutput(BaseModel):
    """
    Final verdict. Receives every prior agent's output.
    Computes its own confidence (replaces Confidence agent).
    Sets manual_review_required (replaces Human Review agent).
    Never rejects because of a single high score.
    """
    status: str = Field(..., description="'success' or 'error'")
    summary: str = Field(..., description="Executive summary of the decision")
    confidence: int = Field(..., ge=0, le=100, description="Overall pipeline confidence 0-100")
    claim_status: ClaimStatus = Field(..., description="supported, contradicted, or not_enough_information")
    manual_review_required: bool = Field(False, description="True if confidence<70, conflicting evidence, or severe fraud")
    escalation_reason: Optional[str] = Field(None, description="Why manual review is needed, or null")
    justification: str = Field(..., description="Detailed multi-sentence explanation of the decision")

    @classmethod
    def from_failure(cls, error_reason: str) -> "DecisionOutput":
        """
        The honest error state.

        When the pipeline cannot reach a grounded verdict — LLM unavailable, no usable
        evidence, a branch that died — we say so. We never synthesise a verdict. The
        claim goes to a human with the real reason attached.
        """
        return cls(
            status="error",
            summary="Automated verification could not complete.",
            confidence=0,
            claim_status="not_enough_information",
            manual_review_required=True,
            escalation_reason=error_reason,
            justification=(
                f"No automated verdict was reached because {error_reason} "
                f"This claim requires manual review; no inference was made from the unavailable evidence."
            ),
        )


# ─── Branch failure placeholder (feedback #4: handle parallel branch failures) ─

class BranchFailureOutput(BaseModel):
    """
    Returned when a parallel branch fails (timeout, 429, exception).

    Downstream agents treat these as 'unknown' — never as 'fine'. A failed branch can
    only ever weaken a verdict toward not_enough_information; it can never support one.
    """
    status: str = Field(default="failed", description="Always 'failed'")
    summary: str = Field(default="", description="Error description")
    error: str = Field(default="", description="Exception message")
    error_type: str = Field(default="", description="Exception class name, for triage")


# ─── LangGraph State ────────────────────────────────────────────────────────

class ClaimsState:
    """
    TypedDict-style annotation for the LangGraph StateGraph.
    
    Defined here for reference. The actual TypedDict is in graph.py
    because LangGraph requires typing.TypedDict (not Pydantic).
    
    Every node reads from this state and writes ONLY its own key.
    No node mutates another node's prior output.
    
    Keys:
      # Inputs
      user_id: str
      image_paths: str
      user_claim: str
      claim_object: str
      user_history: Dict[str, Any]
      evidence_rules: Dict[str, Any]
      images: List[Any]  # PIL Image objects
      
      # Agent outputs
      image_validation: Dict[str, Any]  # ImageValidatorOutput
      ingestion: Dict[str, Any]         # ClaimIngestionOutput
      vision: Dict[str, Any]            # VisionAnalysisOutput  | BranchFailureOutput
      policy: Dict[str, Any]            # PolicyVerificationOutput | BranchFailureOutput
      similar_claims: Dict[str, Any]    # SimilarClaimsOutput   | BranchFailureOutput
      user_risk: Dict[str, Any]         # UserRiskOutput        | BranchFailureOutput
      fraud: Dict[str, Any]             # FraudReviewOutput
      decision: Dict[str, Any]          # DecisionOutput
      
      # Audit trail (append-only via Annotated[List, add])
      audit_logs: List[Dict[str, Any]]
      timeline: List[str]
    """
    pass
