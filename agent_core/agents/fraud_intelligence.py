from typing import Dict, Any, List
from agent_core.schemas.models import FraudIntelligenceOutput

def run_fraud_intelligence_agent(
    claim_text: str,
    claim_understanding: Dict[str, Any],
    vision_analysis: Dict[str, Any],
    quality_flags: List[str],
    user_risk_score: int
) -> FraudIntelligenceOutput:
    """
    Deterministic Fraud Intelligence Agent.
    Evaluates fraud signals and calculates a fraud score using exact heuristics.
    """
    score = 0
    flags = []
    explanations = []
    
    text_lower = claim_text.lower()
    
    # 1. Prompt Injection Detection
    injection_terms = ["ignore instructions", "ignore all instructions", "skip manual review", "auto-approve", "mark this row supported", "skip verification"]
    if any(term in text_lower for term in injection_terms):
        score += 40
        flags.append("text_instruction_present")
        explanations.append("Customer chat log contains prompt injection attempt trying to bypass policies.")
        
    # 2. Pressure Tactics Detection
    pressure_terms = ["escalate publicly", "reopen tickets", "reopen tickets until someone approves", "threaten", "litigation", "sue you"]
    if any(term in text_lower for term in pressure_terms):
        score += 25
        flags.append("pressure_tactics")
        explanations.append("Customer is using pressure tactics or litigation threats to force approval.")
        
    # 3. Image Manipulations QA
    if "possible_manipulation" in quality_flags:
        score += 55
        flags.append("possible_manipulation")
        explanations.append("Evidence photo was flagged for potential digital manipulation or tampering.")
        
    # 4. Wrong Object QA
    if "wrong_object" in quality_flags:
        score += 60
        flags.append("wrong_object")
        explanations.append("The photo shows an entirely different object from what was submitted in the claim.")
        
    # 5. Wrong Object Part QA
    if "wrong_object_part" in quality_flags or "wrong_angle" in quality_flags:
        score += 15
        flags.append("wrong_object_part")
        explanations.append("The photo shows the wrong part of the object or is taken from an uninspectable angle.")
        
    # 6. Claim Mismatch (Claimed vs Detected)
    claimed_issue = claim_understanding.get("claimed_issue", "unknown").lower()
    detected_issue = vision_analysis.get("issue_type", "unknown").lower()
    claimed_part = claim_understanding.get("claimed_part", "unknown").lower()
    detected_part = vision_analysis.get("object_part", "unknown").lower()
    
    damage_detected = vision_analysis.get("damage_detected", False)
    
    if damage_detected:
        if claimed_issue != detected_issue and detected_issue != "none" and detected_issue != "unknown":
            score += 30
            flags.append("claim_mismatch")
            explanations.append(f"Claim mismatch: customer claimed '{claimed_issue}' but visual analysis detected '{detected_issue}'.")
    else:
        # Damage claimed but nothing visible on clean, usable images
        invalidating_flags = ["wrong_object", "cropped_or_obstructed"]
        has_invalidating_flag = any(f in quality_flags for f in invalidating_flags)
        if not has_invalidating_flag and claimed_issue in ["scratch", "crack", "dent", "broken_part", "stain", "crushed_packaging", "torn_packaging", "water_damage"]:
            score += 25
            flags.append("damage_not_visible")
            explanations.append(f"The claimed {claimed_part} is visible in the photo, but no physical damage or '{claimed_issue}' is visible.")
            
    # 7. User Risk Correlation
    if user_risk_score > 70:
        score += 15
        flags.append("high_user_risk_correlation")
        explanations.append("This user has a history of high rejection rates, elevating overall fraud likelihood.")
        
    # Cap score
    score = min(max(score, 0), 100)
    
    if not flags:
        flags.append("none")
        explanations.append("No fraud signals or inconsistencies were detected between claim details and visual evidence.")
        
    return FraudIntelligenceOutput(
        fraud_score=score,
        fraud_flags=flags,
        explanation=" | ".join(explanations)
    )
