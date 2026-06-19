from pydantic import BaseModel, Field
from typing import Dict, Any, List

class ConfidenceOutput(BaseModel):
    confidence_score: int = Field(..., description="Confidence score from 0 to 100")
    explanation: str = Field(..., description="Explanation of how the confidence score was derived")

def run_confidence_agent(
    image_valid: bool,
    quality_flags: List[str],
    evidence_standard_met: bool,
    fraud_score: int,
    user_risk_score: int,
    damage_detected: bool
) -> ConfidenceOutput:
    score = 95  # Base confidence for clear, matching cases
    explanations = []
    
    # 1. Image Validity check
    if not image_valid:
        score -= 40
        explanations.append("Images are marked invalid or unusable (e.g., cropped, tampered, or wrong object).")
        
    # 2. Quality Flags adjustments
    if "blurry_image" in quality_flags:
        score -= 10
        explanations.append("Blurry image quality reduces visual precision.")
    if "wrong_angle" in quality_flags:
        score -= 20
        explanations.append("Camera angle is not optimal to evaluate the claimed part.")
    if "low_light_or_glare" in quality_flags:
        score -= 10
        explanations.append("Poor lighting or glare makes analysis less reliable.")
        
    # 3. Evidence Compliance check
    if not evidence_standard_met:
        score -= 20
        explanations.append("Evidence standards defined by policy are not fully met.")
        
    # 4. Fraud Score impact
    if fraud_score > 80:
        score -= 50
        explanations.append("Critical fraud flags or text injections severely damage assessment trust.")
    elif fraud_score > 50:
        score -= 30
        explanations.append("Significant fraud indicators or inconsistencies reduce trust.")
    elif fraud_score > 20:
        score -= 15
        explanations.append("Minor claims mismatch or user history risk noted.")
        
    # 5. User Risk impact (mild adjustments, history shouldn't override visual evidence directly)
    if user_risk_score > 80:
        score -= 10
        explanations.append("User has an extremely high historical risk profile.")
    elif user_risk_score > 50:
        score -= 5
        explanations.append("User history contains prior rejections.")

    # 6. Safety bounds
    score = min(max(score, 0), 100)
    
    if score >= 90:
        explanations.append("High confidence: evidence is clear, compliant, and free of risk signals.")
    elif score >= 70:
        explanations.append("Moderate confidence: minor issues exist but evidence is generally acceptable.")
    else:
        explanations.append("Low confidence: escalation to manual review is recommended.")
        
    return ConfidenceOutput(
        confidence_score=score,
        explanation=" | ".join(explanations)
    )
