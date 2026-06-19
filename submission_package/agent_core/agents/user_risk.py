import csv
import os
from typing import Dict, Any, List
from agent_core.schemas.models import UserRiskOutput

def run_user_risk_agent(user_id: str, user_history: dict | None = None) -> UserRiskOutput:
    """User Risk Agent — evaluates customer risk profiles based on history and behaviors."""
    user_record = user_history
    
    if not user_record:
        # Fallback to loading CSV directly from default location
        data_paths = [
            os.path.join(os.path.dirname(__file__), "../data/user_history.csv"),
            os.path.join(os.path.dirname(__file__), "../../claims/user_history.csv"),
            "claims/user_history.csv",
            "agent-core/data/user_history.csv",
        ]
        for p in data_paths:
            if os.path.exists(p):
                with open(p, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("user_id") == user_id:
                            user_record = row
                            break
                if user_record:
                    break
                    
    if not user_record:
        return UserRiskOutput(
            user_risk_score=10,
            risk_flags=["none"],
            explanation=f"No claim history found for user {user_id}. Assumed new user with default low risk."
        )
        
    # Parse record values
    try:
        claim_count = int(user_record.get("claim_count", 0))
        rejected_claims = int(user_record.get("rejected_claims", 0))
        manual_review_history = int(user_record.get("manual_review_history", 0))
    except ValueError:
        claim_count = 0
        rejected_claims = 0
        manual_review_history = 0
        
    history_flags_str = user_record.get("history_flags", "none")
    history_flags = [f.strip() for f in history_flags_str.split(";") if f.strip() and f.strip() != "none"]
    
    # Calculate score
    score = 10  # default base
    flags = []
    
    if claim_count > 5:
        score += 15
    if claim_count > 0:
        rejection_rate = rejected_claims / claim_count
        if rejection_rate > 0.5:
            score += 35
            flags.append("high_rejection_rate")
        elif rejection_rate > 0.2:
            score += 15
            
    if manual_review_history > 3:
        score += 20
        flags.append("frequent_manual_reviews")
        
    for h_flag in history_flags:
        if h_flag == "suspicious_claims":
            score += 30
            flags.append("user_history_risk")
        elif h_flag == "prior_suspicious_evidence":
            score += 35
            flags.append("user_history_risk")
        elif h_flag == "severity_exaggeration":
            score += 25
            flags.append("user_history_risk")
        elif h_flag == "blurry_uploads_frequent":
            score += 15
            flags.append("unreliable_uploads")
        elif h_flag == "harassment_threats":
            score += 40
            flags.append("abusive_behavior")
        elif h_flag == "pushy_behavior":
            score += 15
            flags.append("abusive_behavior")
            
    # Cap score
    score = min(max(score, 0), 100)
    
    # Generate explanation
    profile = "Low Risk"
    if score >= 75:
        profile = "High Risk"
    elif score >= 40:
        profile = "Medium Risk"
        
    if not flags:
        flags.append("none")
        
    explanation = (
        f"User has filed {claim_count} claims, with {rejected_claims} rejections and {manual_review_history} manual reviews. "
        f"Flags: {history_flags_str}. Risk profile is evaluated as {profile} ({score}/100)."
    )
    
    return UserRiskOutput(
        user_risk_score=score,
        risk_flags=flags,
        explanation=explanation
    )
