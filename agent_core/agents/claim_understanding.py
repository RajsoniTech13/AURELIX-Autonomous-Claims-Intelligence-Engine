"""
Claim Understanding Agent — extracts structured claim info from conversation text.
Text-only agent — no images needed.
"""
from agent_core.services.llm import call_structured_llm
from agent_core.schemas.models import ClaimUnderstandingOutput
from agent_core.prompts.templates import CLAIM_UNDERSTANDING_PROMPT as PROMPT


def run_claim_understanding_agent(conversation: str, claim_object: str) -> ClaimUnderstandingOutput:
    """Extract structured claim understanding from conversation text using LLM."""
    return call_structured_llm(
        prompt_template=PROMPT,
        variables={"conversation": conversation, "claim_object": claim_object},
        response_model=ClaimUnderstandingOutput,
    )
