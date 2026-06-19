from typing import List
from agent_core.schemas.models import HumanReviewOutput

def run_human_review_agent(
    confidence_score: int,
    fraud_score: int,
    image_valid: bool,
    quality_flags: List[str],
    user_risk_score: int,
    claim_status: str
) -> HumanReviewOutput:
    reasons = []
    
    # Trigger 1: Confidence below 70
    if confidence_score < 70:
        reasons.append(f"Confidence score is {confidence_score}/100, which is below the auto-approval threshold of 70.")
        
    # Trigger 2: Fraud Score above 50
    if fraud_score > 50:
        reasons.append(f"High fraud risk score of {fraud_score}/100 detected.")
        
    # Trigger 3: Image invalid or manipulated
    if not image_valid:
        reasons.append("Evidence photo was flagged as invalid or unusable.")
    if "possible_manipulation" in quality_flags:
        reasons.append("Possible digital manipulation or tampering detected in the submitted image.")
        
    # Trigger 4: Prompt Injection or Abusive Behavior
    if "text_instruction_present" in quality_flags or "pressure_tactics" in quality_flags:
        reasons.append("Security flags triggered (prompt injection attempt or pressure tactics detected in chat text).")

    # Trigger 5: Claim mismatch or wrong object part
    if "claim_mismatch" in quality_flags or "wrong_object_part" in quality_flags:
        reasons.append("Mismatch between claimed damage details and actual visual features detected.")

    # Trigger 6: Extreme user risk score
    if user_risk_score > 80:
        reasons.append(f"User risk profile is critically high ({user_risk_score}/100).")

    # Determine if escalation is required
    manual_review_required = len(reasons) > 0
    
    if manual_review_required:
        escalation_reason = " | ".join(reasons)
    else:
        escalation_reason = "none"
        
    return HumanReviewOutput(
        manual_review_required=manual_review_required,
        escalation_reason=escalation_reason
    )
