"""
Fraud Review Agent — Gemini, conservative reasoning over aggregated JSON.

CRITICAL: Fraud is NEVER assumed. Requires objective evidence.
If no objective indicators exist, fraud_score MUST be 5-15.

This replaces the old deterministic fraud_intelligence.py with LLM reasoning
so the agent can provide richer, more nuanced explanations.
"""
import json
from typing import Dict, Any

from agent_core.services.gemini_client import call_gemini_text, compute_cache_key
from agent_core.schemas.models import FraudReviewOutput
from agent_core.prompts.templates import FRAUD_REVIEW_PROMPT


def run_fraud_review_agent(
    claim_text: str,
    ingestion: Dict[str, Any],
    vision: Dict[str, Any],
    policy: Dict[str, Any],
    user_risk: Dict[str, Any],
    user_id: str = "",
) -> FraudReviewOutput:
    """
    Gemini-powered fraud assessment.
    Receives aggregated JSON from all prior agents as context.
    """
    prompt = FRAUD_REVIEW_PROMPT.format(
        claim_text=claim_text,
        ingestion_json=json.dumps(ingestion, default=str),
        vision_json=json.dumps(vision, default=str),
        policy_json=json.dumps(policy, default=str),
        user_risk_json=json.dumps(user_risk, default=str),
    )

    cache_key = compute_cache_key(
        agent_name="fraud_review",
        user_id=user_id,
        claim_text=claim_text,
    )

    return call_gemini_text(
        prompt=prompt,
        response_model=FraudReviewOutput,
        cache_key=cache_key,
    )
