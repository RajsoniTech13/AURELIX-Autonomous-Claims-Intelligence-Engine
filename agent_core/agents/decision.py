from typing import Dict, Any, List
from agent_core.schemas.models import DecisionOutput

def run_decision_agent(
    claim_understanding: Dict[str, Any],
    vision_analysis: Dict[str, Any],
    quality_flags: List[str],
    image_valid: bool,
    evidence_standard_met: bool,
    evidence_compliance_reason: str,
    fraud_score: int,
    user_risk_score: int,
    similar_claims_context: str
) -> DecisionOutput:
    """
    Deterministic Decision Agent.
    Evaluates final status (supported, contradicted, or not_enough_information) 
    and generates grounded, detailed justifications.
    """
    part = claim_understanding.get("claimed_part", "claimed part").lower()
    claimed_issue = claim_understanding.get("claimed_issue", "issue").lower()
    claim_object = claim_understanding.get("object", "object").lower()
    
    detected_issue = vision_analysis.get("issue_type", "none").lower()
    detected_part = vision_analysis.get("object_part", "none").lower()
    damage_detected = vision_analysis.get("damage_detected", False)
    
    # 0. Evaluate Contradicted / Wrong Object
    if "wrong_object" in quality_flags:
        return DecisionOutput(
            claim_status="contradicted",
            justification="The submitted image shows a completely different object, which contradicts the claim."
        )
        
    # 1. Evaluate Not Enough Information (Invalid Images / Compliance Failures)
    is_critically_invalid = not image_valid and not ("possible_manipulation" in quality_flags)
    
    if is_critically_invalid:
        reasons = []
        if "cropped_or_obstructed" in quality_flags:
            reasons.append("the claimed part is cropped or obstructed in the image")
        if "wrong_object" in quality_flags:
            reasons.append("the image shows a completely wrong object")
        if "possible_manipulation" in quality_flags:
            reasons.append("the image shows suspicious texture modifications or digital tampering")
        if not reasons:
            reasons.append("the image quality is insufficient for review")
            
        reason_str = " and ".join(reasons)
        justification = f"The claim cannot be verified because {reason_str}. The submitted evidence is insufficient to confirm the claim."
        return DecisionOutput(claim_status="not_enough_information", justification=justification)
        
    if not evidence_standard_met:
        justification = f"Evidence standard not met: {evidence_compliance_reason}"
        return DecisionOutput(claim_status="not_enough_information", justification=justification)
        
    if "wrong_angle" in quality_flags:
        justification = f"The submitted image does not show the claimed {part} due to a wrong camera angle, so the claim cannot be verified."
        return DecisionOutput(claim_status="not_enough_information", justification=justification)

    # 2. Evaluate Contradicted (Visual Evidence Contradicts the Claim)
    is_contradicted = False
    contradiction_reason = ""
    
    # Text instruction injection or manipulation attempt
    if fraud_score >= 40 and "text_instruction_present" in quality_flags:
        is_contradicted = True
        contradiction_reason = f"The claim is contradicted due to clear prompt injection phrases instructing the system to bypass evaluation policies."
    elif not damage_detected:
        is_contradicted = True
        contradiction_reason = f"The submitted image shows the claimed {part} clearly, but no physical damage or {claimed_issue} is visible."
    elif claimed_issue != detected_issue and detected_issue != "none" and detected_issue != "unknown":
        is_contradicted = True
        contradiction_reason = f"The image shows only minor {detected_issue} on the {part}, which contradicts the customer's claim of severe {claimed_issue}."
        
    if is_contradicted:
        return DecisionOutput(claim_status="contradicted", justification=contradiction_reason)

    # 3. Evaluate Supported (Visual Evidence matches Claim Details)
    if damage_detected:
        supporting_img_str = "the submitted image"
        if vision_analysis.get("supporting_image_ids"):
            supporting_img_str = f"image {vision_analysis.get('supporting_image_ids')[0]}"
            
        justification = f"The {supporting_img_str} clearly shows a {detected_issue} on the {part} matching the user's claim."
        
        if "possible_manipulation" in quality_flags or fraud_score > 50:
            justification += " Note: authenticity concerns or risk flags require manual review."
            
        return DecisionOutput(claim_status="supported", justification=justification)
        
    # 4. Fallback Default
    return DecisionOutput(
        claim_status="not_enough_information",
        justification="The claim could not be conclusively verified with the submitted evidence."
    )
