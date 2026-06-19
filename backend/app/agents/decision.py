from pydantic import BaseModel, Field
from typing import Dict, Any, List
from backend.app.agents.llm import call_structured_llm

class DecisionOutput(BaseModel):
    claim_status: str = Field(..., description="Final claim verdict: supported, contradicted, or not_enough_information")
    justification: str = Field(..., description="A detailed explanation of why the final verdict was reached")

PROMPT = """
You are a Senior Insurance Claims Decision Engine.
Review the consolidated inputs and make a final verdict.

Allowed status values:
- supported: Visual evidence clearly confirms the claimed damage on the correct part.
- contradicted: Visual evidence contradicts the claim (e.g., claimed damage is not present on a clear photo, or is extremely exaggerated like claimed shatter but is just a minor scratch).
- not_enough_information: The image is invalid, cropped, blurry, or showing the wrong part, making it impossible to verify the claim.

Inputs:
- Claim Understanding: {claim_understanding}
- Vision Analysis: {vision_analysis}
- Image Quality Flags: {quality_flags}
- Image Valid: {image_valid}
- Evidence Standard Met: {evidence_standard_met}
- Evidence Compliance Reason: {evidence_compliance_reason}
- Fraud Score: {fraud_score}
- User Risk Score: {user_risk_score}

Determine the claim status and write a professional, detailed justification. Explain:
1. What image/evidence was evaluated
2. What was detected
3. Why the decision was reached
"""

def fallback_parser(variables: Dict[str, Any], response_model) -> DecisionOutput:
    understanding = variables["claim_understanding"]
    vision = variables["vision_analysis"]
    quality_flags = variables["quality_flags"]
    image_valid = variables["image_valid"]
    evidence_standard_met = variables["evidence_standard_met"]
    compliance_reason = variables["evidence_compliance_reason"]
    fraud_score = variables["fraud_score"]
    
    # 1. Check Not Enough Information
    if not image_valid:
        # Check reasons
        reasons = []
        if "cropped_or_obstructed" in quality_flags:
            reasons.append("the claimed part is cropped or obstructed in the image")
        if "wrong_object" in quality_flags:
            reasons.append("the image shows a completely wrong object")
        if "possible_manipulation" in quality_flags:
            reasons.append("the image shows suspicious texture modifications or tampering")
        
        if not reasons:
            reasons.append("the image quality is insufficient for review")
            
        reason_str = " and ".join(reasons)
        justification = f"The claim cannot be verified because {reason_str}. The submitted evidence is insufficient to confirm the claim."
        return DecisionOutput(claim_status="not_enough_information", justification=justification)
        
    if not evidence_standard_met and "wrong_angle" in quality_flags:
        justification = f"The submitted image does not show the claimed part (wrong camera angle), so the claim cannot be verified."
        return DecisionOutput(claim_status="not_enough_information", justification=justification)

    # 2. Check Contradicted
    # - If vision analysis explicitly says contradicted or if we find contradiction features
    # - e.g. claim mismatch, damage not visible
    damage_detected = vision.get("damage_detected", False)
    detected_issue = vision.get("issue_type", "unknown").lower()
    claimed_issue = understanding.get("claimed_issue", "unknown").lower()
    part = understanding.get("claimed_part", "unknown").lower()
    
    # Check for contradictions
    is_contradicted = False
    contradiction_reason = ""
    
    if "claim_mismatch" in compliance_reason or "claim_mismatch" in str(quality_flags) or "claim_mismatch" in str(variables.get("fraud_score", 0)):
        is_contradicted = True
        contradiction_reason = f"The image shows only minor {detected_issue} on the {part}, which contradicts the customer's claim of severe damage."
    elif not damage_detected and image_valid and evidence_standard_met:
        is_contradicted = True
        contradiction_reason = f"The submitted image shows the claimed {part} clearly, but no physical damage or {claimed_issue} is visible."
    elif detected_issue == "none" or (claimed_issue == "torn_packaging" and detected_issue == "none"):
        is_contradicted = True
        contradiction_reason = f"The package seal is clearly visible and intact in the images. There is no sign of torn packaging or tampered seals."
        
    if is_contradicted:
        return DecisionOutput(
            claim_status="contradicted",
            justification=contradiction_reason
        )

    # 3. Supported
    if damage_detected:
        supporting_img_str = "the submitted image"
        if vision.get("supporting_image_ids"):
            supporting_img_str = f"image {vision.get('supporting_image_ids')[0]}"
            
        justification = f"The {supporting_img_str} clearly shows a {detected_issue} on the {part} matching the user's claim."
        
        # Add risk/authenticity warnings if any
        if "possible_manipulation" in quality_flags or fraud_score > 50:
            justification += " Note: authenticity concerns or risk flags require further review."
            
        return DecisionOutput(
            claim_status="supported",
            justification=justification
        )
        
    # Default fallback
    return DecisionOutput(
        claim_status="not_enough_information",
        justification="The claim could not be conclusively verified with the submitted evidence."
    )

def run_decision_agent(
    claim_understanding: Dict[str, Any],
    vision_analysis: Dict[str, Any],
    quality_flags: List[str],
    image_valid: bool,
    evidence_standard_met: bool,
    evidence_compliance_reason: str,
    fraud_score: int,
    user_risk_score: int
) -> DecisionOutput:
    return call_structured_llm(
        prompt_template=PROMPT,
        variables={
            "claim_understanding": claim_understanding,
            "vision_analysis": vision_analysis,
            "quality_flags": quality_flags,
            "image_valid": image_valid,
            "evidence_standard_met": evidence_standard_met,
            "evidence_compliance_reason": evidence_compliance_reason,
            "fraud_score": fraud_score,
            "user_risk_score": user_risk_score
        },
        response_model=DecisionOutput,
        fallback_parser_func=fallback_parser
    )
