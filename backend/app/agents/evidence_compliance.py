import csv
import os
from pydantic import BaseModel, Field
from typing import Dict, Any, List
from backend.app.config import settings

class EvidenceComplianceOutput(BaseModel):
    evidence_standard_met: bool = Field(..., description="Does the claim meet the minimum evidence standards defined in the policy?")
    reason: str = Field(..., description="Justification explaining why the standards are or are not met")

def run_evidence_compliance_agent(
    claim_object: str,
    claimed_part: str,
    image_paths: str,
    quality_flags: List[str]
) -> EvidenceComplianceOutput:
    # 1. Parse image paths
    paths = [p.strip() for p in image_paths.split(";") if p.strip()]
    uploaded_count = len(paths)
    
    # 2. Read evidence requirements CSV dynamically
    req_path = settings.EVIDENCE_REQUIREMENTS_CSV
    policy = None
    
    if os.path.exists(req_path):
        with open(req_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("claim_object", "").lower() == claim_object.lower():
                    policy = row
                    break
                    
    if not policy:
        # Fallback default rules if CSV not found or matching row not found
        return EvidenceComplianceOutput(
            evidence_standard_met=True,
            reason=f"No policy rules found for {claim_object}. Standard assumed met."
        )
        
    # Extract policy constraints
    try:
        req_count = int(policy.get("required_image_count", 1))
    except ValueError:
        req_count = 1
        
    allowed_parts = [p.strip().lower() for p in policy.get("required_visibility", "").split(";") if p.strip()]
    if not allowed_parts:
        allowed_parts = [p.strip().lower() for p in policy.get("required_visibility", "").split(",") if p.strip()]
        
    # Perform checks
    # Check 1: Image Count
    if uploaded_count < req_count:
        return EvidenceComplianceOutput(
            evidence_standard_met=False,
            reason=f"Evidence standard not met: policy requires at least {req_count} images for a {claim_object} claim, but only {uploaded_count} was submitted."
        )
        
    # Check 2: Part visibility in policy
    # If the claimed part is totally outside the allowed parts of the policy
    # (e.g. claiming engine damage on a car, but policy only lists body/bumper/windshield/mirror/hood)
    clean_part = claimed_part.lower().strip()
    # Normalize part names
    matched_visibility = False
    for p in allowed_parts:
        if p in clean_part or clean_part in p:
            matched_visibility = True
            break
            
    if not matched_visibility and allowed_parts:
        return EvidenceComplianceOutput(
            evidence_standard_met=False,
            reason=f"Evidence standard not met: the claimed part '{claimed_part}' is not covered under the visibility guidelines for {claim_object} claims."
        )
        
    # Check 3: Check quality flags (wrong_angle or cropped/obstructed might violate visibility)
    if "wrong_angle" in quality_flags:
        # Note: in sample_claims, user_006 has evidence_standard_met = false because "headlight not visible"
        return EvidenceComplianceOutput(
            evidence_standard_met=False,
            reason="Evidence standard not met: the submitted image does not show the claimed part due to a wrong camera angle."
        )
        
    if "cropped_or_obstructed" in quality_flags:
        return EvidenceComplianceOutput(
            evidence_standard_met=False,
            reason="Evidence standard not met: the claimed object part is cropped out or obstructed in the photo."
        )

    # All checks passed
    reason_parts = []
    if claim_object == "car":
        reason_parts.append("The bumper/windshield/door/mirror/hood is visible and meets policy requirements.")
    elif claim_object == "laptop":
        reason_parts.append("The laptop is visible and meets the screen/keyboard/hinge/trackpad/body visibility guidelines.")
    else:
        reason_parts.append(f"The package/box is visible and meets the outer packaging guidelines.")
        
    return EvidenceComplianceOutput(
        evidence_standard_met=True,
        reason=" ".join(reason_parts)
    )
