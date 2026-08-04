"""
Claim Ingestion Agent — Gemini, text-only.

Parses claim text into structured fields.
Never analyzes images. Never calculates risk.
"""
from agent_core.services.gemini_client import call_gemini_text, compute_cache_key
from agent_core.schemas.models import ClaimIngestionOutput
from agent_core.prompts.templates import CLAIM_INGESTION_PROMPT


def run_claim_ingestion_agent(
    conversation: str,
    claim_object: str,
    user_id: str = "",
) -> ClaimIngestionOutput:
    """Extract structured claim information from conversation text using Gemini."""
    prompt = CLAIM_INGESTION_PROMPT.format(
        conversation=conversation,
        claim_object=claim_object,
    )

    cache_key = compute_cache_key(
        agent_name="claim_ingestion",
        user_id=user_id,
        claim_text=conversation,
    )

    return call_gemini_text(
        prompt=prompt,
        response_model=ClaimIngestionOutput,
        cache_key=cache_key,
    )
