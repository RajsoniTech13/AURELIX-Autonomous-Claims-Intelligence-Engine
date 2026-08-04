"""
Decision Agent — Gemini, final call.

Absorbs the responsibilities of the former Confidence and Human Review agents:
- Computes its own confidence score (0-100).
- Sets manual_review_required flag with escalation_reason.

Never rejects because of a single high score. Weighs all signals together.
"""
import json
from typing import Dict, Any

from agent_core.services.gemini_client import call_gemini_text, compute_cache_key
from agent_core.schemas.models import DecisionOutput
from agent_core.prompts.templates import DECISION_PROMPT


def run_decision_agent(
    ingestion: Dict[str, Any],
    vision: Dict[str, Any],
    policy: Dict[str, Any],
    similar_claims: Dict[str, Any],
    user_risk: Dict[str, Any],
    fraud: Dict[str, Any],
    user_id: str = "",
    claim_text: str = "",
) -> DecisionOutput:
    """
    Final verdict combining all prior agent outputs via Gemini reasoning.
    """
    # Build similar claims context string
    similar_context = similar_claims.get("summary", "No similar claims found.")

    prompt = DECISION_PROMPT.format(
        similar_claims_context=similar_context,
        ingestion_json=json.dumps(ingestion, default=str),
        vision_json=json.dumps(vision, default=str),
        policy_json=json.dumps(policy, default=str),
        user_risk_json=json.dumps(user_risk, default=str),
        fraud_json=json.dumps(fraud, default=str),
    )

    cache_key = compute_cache_key(
        agent_name="decision",
        user_id=user_id,
        claim_text=claim_text,
    )

    return call_gemini_text(
        prompt=prompt,
        response_model=DecisionOutput,
        cache_key=cache_key,
    )
