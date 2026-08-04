"""
User Risk Agent — DETERMINISTIC, database-only.

Reads user_history table. Returns LOW / MEDIUM / HIGH risk level.
User history NEVER overrides visual evidence — it only contributes risk context.
"""
import csv
import os
from typing import Dict, Any, List, Optional
from agent_core.schemas.models import UserRiskOutput


def run_user_risk_agent(
    user_id: str,
    user_history: Optional[Dict[str, Any]] = None,
) -> UserRiskOutput:
    """
    Evaluate user risk profile from claim history.
    Deterministic — no LLM call. Returns certainty='deterministic'.
    """
    record = user_history

    # Fallback: load from CSV
    if not record:
        data_paths = [
            os.path.join(os.path.dirname(__file__), "../data/user_history.csv"),
            "agent_core/data/user_history.csv",
        ]
        for p in data_paths:
            if os.path.exists(p):
                with open(p, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("user_id") == user_id:
                            record = row
                            break
                if record:
                    break

    # No history found — new user, low risk
    if not record:
        return UserRiskOutput(
            status="no_history",
            summary=f"No claim history for user {user_id}. Default low risk.",
            risk_level="LOW",
            risk_score=10,
            risk_flags=[],
        )

    # ── Parse fields ──
    try:
        claim_count = int(record.get("claim_count", 0))
        rejected_claims = int(record.get("rejected_claims", 0))
        manual_review_history = int(record.get("manual_review_history", 0))
    except ValueError:
        claim_count = rejected_claims = manual_review_history = 0

    history_flags_str = record.get("history_flags", "none")
    history_flags = [
        f.strip() for f in history_flags_str.split(";")
        if f.strip() and f.strip() != "none"
    ]

    # ── Calculate risk score ──
    score = 10  # base
    flags: List[str] = []

    # Claim volume
    if claim_count > 5:
        score += 15

    # Rejection rate
    if claim_count > 0:
        rejection_rate = rejected_claims / claim_count
        if rejection_rate > 0.5:
            score += 35
            flags.append("high_rejection_rate")
        elif rejection_rate > 0.2:
            score += 15

    # Manual review frequency
    if manual_review_history > 3:
        score += 20
        flags.append("frequent_manual_reviews")

    # History flags
    flag_scores = {
        "suspicious_claims": (30, "suspicious_history"),
        "prior_suspicious_evidence": (35, "suspicious_history"),
        "severity_exaggeration": (25, "severity_exaggeration"),
        "blurry_uploads_frequent": (15, "unreliable_uploads"),
        "harassment_threats": (40, "abusive_behavior"),
        "pushy_behavior": (15, "abusive_behavior"),
    }

    for h_flag in history_flags:
        if h_flag in flag_scores:
            pts, flag_name = flag_scores[h_flag]
            score += pts
            if flag_name not in flags:
                flags.append(flag_name)

    # Cap score
    score = min(max(score, 0), 100)

    # ── Determine risk level ──
    if score >= 70:
        risk_level = "HIGH"
    elif score >= 40:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    summary = (
        f"User {user_id}: {claim_count} claims, {rejected_claims} rejections, "
        f"{manual_review_history} manual reviews. Risk: {risk_level} ({score}/100)."
    )

    return UserRiskOutput(
        status="success",
        summary=summary,
        risk_level=risk_level,
        risk_score=score,
        risk_flags=flags,
    )
