from pydantic import BaseModel, Field
from typing import Dict, Any
from backend.app.agents.llm import call_structured_llm

class ClaimUnderstandingOutput(BaseModel):
    object: str = Field(..., description="The object of the claim: car, laptop, or package")
    claimed_issue: str = Field(..., description="The type of damage claimed (e.g. scratch, crack, dent, broken_part, stain, crushed_packaging, torn_packaging, water_damage, missing_contents)")
    claimed_part: str = Field(..., description="The specific part of the object claimed to be damaged")
    summary: str = Field(..., description="A short summary of the claim conversation")

PROMPT = """
You are an expert Insurance Claims Intake Agent. Your job is to extract structured information from the customer-support chat transcript.

Analyze the transcript below and output:
1. The object category (must be one of: car, laptop, package)
2. The claimed issue type (e.g. scratch, crack, dent, broken_part, stain, crushed_packaging, torn_packaging, water_damage, missing_contents, or similar)
3. The specific object part that is claimed to be damaged (e.g. front_bumper, rear_bumper, windshield, side_mirror, door, hood, screen, keyboard, hinge, trackpad, body, corner, lid, package_corner, seal, box, package_side, contents, label, etc.)
4. A concise 1-2 sentence summary of the conversation.

Claim Object: {claim_object}
Conversation:
{conversation}
"""

def fallback_parser(variables: Dict[str, Any], response_model) -> ClaimUnderstandingOutput:
    conversation = variables["conversation"].lower()
    claim_object = variables["claim_object"].lower()
    
    # 1. Determine Object
    obj = "car"
    if "laptop" in conversation or "screen" in conversation or "keyboard" in conversation or "hinge" in conversation or "trackpad" in conversation or claim_object == "laptop":
        obj = "laptop"
    elif "package" in conversation or "parcel" in conversation or "delivery box" in conversation or "shipping box" in conversation or claim_object == "package":
        obj = "package"
    else:
        obj = claim_object
        
    # 2. Determine Part & Issue
    part = "unknown"
    issue = "unknown"
    
    # Parts
    if "bumper" in conversation:
        part = "front_bumper" if "front" in conversation else "rear_bumper"
    elif "windshield" in conversation or "front glass" in conversation:
        part = "windshield"
    elif "mirror" in conversation:
        part = "side_mirror"
    elif "door" in conversation:
        part = "door"
    elif "hood" in conversation:
        part = "hood"
    elif "screen" in conversation or "display" in conversation:
        part = "screen"
    elif "keyboard" in conversation or "keys" in conversation:
        part = "keyboard"
    elif "hinge" in conversation:
        part = "hinge"
    elif "trackpad" in conversation:
        part = "trackpad"
    elif "lid" in conversation:
        part = "lid"
    elif "corner" in conversation:
        part = "corner" if obj == "laptop" else "package_corner"
    elif "seal" in conversation:
        part = "seal"
    elif "label" in conversation:
        part = "label"
    elif "contents" in conversation or "product inside" in conversation or "item inside" in conversation:
        part = "contents"
    elif "box" in conversation:
        part = "box"
    elif "side" in conversation:
        part = "package_side" if obj == "package" else "body"

    # Issues
    if "crack" in conversation or "shatter" in conversation or "broken" in conversation:
        issue = "crack" if ("screen" in conversation or "windshield" in conversation or "glass" in conversation) else "broken_part"
    elif "dent" in conversation:
        issue = "dent"
    elif "scratch" in conversation or "scrape" in conversation:
        issue = "scratch"
    elif "crush" in conversation or "squeeze" in conversation:
        issue = "crushed_packaging"
    elif "torn" in conversation or "opened" in conversation or "tear" in conversation:
        issue = "torn_packaging"
    elif "water" in conversation or "wet" in conversation or "liquid" in conversation or "spill" in conversation or "stain" in conversation:
        issue = "water_damage" if ("package" in conversation or "box" in conversation) else ("stain" if "keyboard" in conversation or "screen" in conversation else "liquid_damage")
    elif "missing" in conversation or "not inside" in conversation:
        issue = "missing_contents"
        
    summary = f"Customer reported damage on the {part} of their {obj}."
    
    return ClaimUnderstandingOutput(
        object=obj,
        claimed_issue=issue,
        claimed_part=part,
        summary=summary
    )

def run_claim_understanding_agent(conversation: str, claim_object: str) -> ClaimUnderstandingOutput:
    return call_structured_llm(
        prompt_template=PROMPT,
        variables={"conversation": conversation, "claim_object": claim_object},
        response_model=ClaimUnderstandingOutput,
        fallback_parser_func=fallback_parser
    )
