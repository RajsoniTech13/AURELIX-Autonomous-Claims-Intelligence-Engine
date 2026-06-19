import csv
import os
from typing import Dict, Any, List
from agent_core.schemas.models import EvidenceRetrievalOutput

def run_evidence_retrieval_agent(
    claim_object: str,
    claimed_part: str,
    image_paths: str,
    quality_flags: List[str],
    evidence_rules: dict | None = None
) -> EvidenceRetrievalOutput:
    """Evidence Compliance Agent — verifies if evidence meets object-specific submission guidelines."""
    paths = [p.strip() for p in image_paths.split(";") if p.strip()]
    uploaded_count = len(paths)
    
    policy = evidence_rules
    
    if not policy:
        # Fallback to loading CSV directly from default location
        data_paths = [
            os.path.join(os.path.dirname(__file__), "../data/evidence_requirements.csv"),
            os.path.join(os.path.dirname(__file__), "../../claims/evidence_requirements.csv"),
            "claims/evidence_requirements.csv",
            "agent-core/data/evidence_requirements.csv",
        ]
        for p in data_paths:
            if os.path.exists(p):
                with open(p, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("claim_object", "").lower() == claim_object.lower():
                            policy = row
                            break
                if policy:
                    break
                    
    if not policy:
        return EvidenceRetrievalOutput(
            evidence_standard_met=True,
            reason=f"No policy rules found for {claim_object}. Standard assumed met."
        )
        
    try:
        req_count = int(policy.get("required_image_count", 1))
    except ValueError:
        req_count = 1
        
    allowed_parts = [p.strip().lower() for p in policy.get("required_visibility", "").split(";") if p.strip()]
    if not allowed_parts:
        allowed_parts = [p.strip().lower() for p in policy.get("required_visibility", "").split(",") if p.strip()]
        
    if uploaded_count < req_count:
        return EvidenceRetrievalOutput(
            evidence_standard_met=False,
            reason=f"Evidence standard not met: policy requires at least {req_count} images for a {claim_object} claim, but only {uploaded_count} was submitted."
        )
        
    clean_part = claimed_part.lower().strip()
    matched_visibility = False
    for p in allowed_parts:
        if p in clean_part or clean_part in p:
            matched_visibility = True
            break
            
    if not matched_visibility and allowed_parts:
        return EvidenceRetrievalOutput(
            evidence_standard_met=False,
            reason=f"Evidence standard not met: the claimed part '{claimed_part}' is not covered under the visibility guidelines for {claim_object} claims."
        )
        
    if "wrong_angle" in quality_flags:
        return EvidenceRetrievalOutput(
            evidence_standard_met=False,
            reason="Evidence standard not met: the submitted image does not show the claimed part due to a wrong camera angle."
        )
        
    if "cropped_or_obstructed" in quality_flags:
        return EvidenceRetrievalOutput(
            evidence_standard_met=False,
            reason="Evidence standard not met: the claimed object part is cropped out or obstructed in the photo."
        )

    if "blurry_image" in quality_flags and uploaded_count == 1:
        return EvidenceRetrievalOutput(
            evidence_standard_met=False,
            reason="Evidence standard not met: the submitted image is too blurry or out of focus to verify the claim."
        )

    reason_parts = []
    if claim_object == "car":
        reason_parts.append("The bumper/windshield/door/mirror/hood is visible and meets policy requirements.")
    elif claim_object == "laptop":
        reason_parts.append("The laptop is visible and meets the screen/keyboard/hinge/trackpad/body visibility guidelines.")
    else:
        reason_parts.append(f"The package/box is visible and meets the outer packaging guidelines.")
        
    return EvidenceRetrievalOutput(
        evidence_standard_met=True,
        reason=" ".join(reason_parts)
    )
