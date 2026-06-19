from pydantic import BaseModel, Field
from typing import List, Dict, Any

class ClaimUnderstandingOutput(BaseModel):
    object: str = Field(..., description="The object of the claim: car, laptop, or package")
    claimed_issue: str = Field(..., description="The type of damage claimed (e.g. scratch, crack, dent, broken_part, stain, crushed_packaging, torn_packaging, water_damage, missing_contents)")
    claimed_part: str = Field(..., description="The specific part of the object claimed to be damaged")
    summary: str = Field(..., description="A short summary of the claim conversation")

class ImageQualityOutput(BaseModel):
    image_valid: bool = Field(..., description="Is the image of sufficient quality to evaluate the claim?")
    quality_flags: List[str] = Field(..., description="List of detected quality issues: blurry_image, cropped_or_obstructed, low_light_or_glare, wrong_angle, wrong_object, wrong_object_part, possible_manipulation")
    reason: str = Field(..., description="Description of the quality checks performed and findings")

class VisionAnalysisOutput(BaseModel):
    damage_detected: bool = Field(..., description="Is any physical damage visible in the images?")
    issue_type: str = Field(..., description="The type of damage detected (e.g. scratch, crack, dent, broken_part, stain, crushed_packaging, torn_packaging, water_damage, missing_contents, or none)")
    object_part: str = Field(..., description="The object part where damage is detected (or none)")
    severity: str = Field(..., description="Estimated severity: none, low, medium, high, or unknown")
    supporting_image_ids: List[str] = Field(..., description="List of image IDs (e.g. ['img_1', 'img_2']) that clearly show the damage")
    justification: str = Field(..., description="Detailed description of what is visible in the images to support this assessment")

class EvidenceRetrievalOutput(BaseModel):
    evidence_standard_met: bool = Field(..., description="Does the claim meet the minimum evidence standards defined in the policy?")
    reason: str = Field(..., description="Justification explaining why the standards are or are not met")

class SimilarClaimMetadata(BaseModel):
    user_id: str
    claim_object: str
    issue_type: str
    object_part: str
    claim_status: str
    similarity_score: float
    justification: str

class SimilarClaimsOutput(BaseModel):
    similar_claims: List[SimilarClaimMetadata] = Field(..., description="List of similar claims retrieved from historical database")
    reasoning_context: str = Field(..., description="Synthesis comparing these claims to the current claim, acting as RAG context")

class UserRiskOutput(BaseModel):
    user_risk_score: int = Field(..., description="Calculated user risk score from 0 to 100")
    risk_flags: List[str] = Field(..., description="List of user risk flags (e.g. user_history_risk, high_rejection_rate)")
    explanation: str = Field(..., description="Detailed explanation of the risk profile")

class FraudIntelligenceOutput(BaseModel):
    fraud_score: int = Field(..., description="Fraud score from 0 to 100")
    fraud_flags: List[str] = Field(..., description="List of fraud signals (e.g. claim_mismatch, possible_manipulation, text_instruction_present, pressure_tactics)")
    explanation: str = Field(..., description="Detailed explanation of detected fraud signals")

class ConfidenceOutput(BaseModel):
    confidence_score: int = Field(..., description="Confidence score from 0 to 100")
    explanation: str = Field(..., description="Explanation of how the confidence score was derived")

class DecisionOutput(BaseModel):
    claim_status: str = Field(..., description="Final claim verdict: supported, contradicted, or not_enough_information")
    justification: str = Field(..., description="A detailed explanation of why the final verdict was reached")

class HumanReviewOutput(BaseModel):
    manual_review_required: bool = Field(..., description="Is manual human review required for this claim?")
    escalation_reason: str = Field(..., description="The reason why this claim was escalated to human review, or none")
