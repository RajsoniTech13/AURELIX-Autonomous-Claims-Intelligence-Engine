"""
Vision Analysis Agent — analyzes images for damage detection.
Dual-mode:
  - Vision mode: receives PIL images → Gemini Vision multimodal analysis
  - Text mode:  no images → LLM reasons from claim text + context only
"""
from typing import List, Optional
from PIL import Image

from agent_core.services.llm import call_structured_llm
from agent_core.services.vision_llm import analyze_images_structured
from agent_core.schemas.models import VisionAnalysisOutput
from agent_core.prompts.templates import (
    VISION_ANALYSIS_PROMPT,
    VISION_WITH_IMAGES_PROMPT,
)


def run_vision_analysis_agent(
    claimed_object: str,
    claimed_part: str,
    user_claim_text: str,
    images: Optional[List[Image.Image]] = None,
    image_paths_str: str = "",
) -> VisionAnalysisOutput:
    """
    Analyze claim images for damage.

    If `images` (PIL objects) are provided, uses Gemini Vision for true pixel analysis.
    Otherwise, falls back to text-only LLM reasoning based on claim context.
    """
    if images and len(images) > 0:
        # ── Vision Mode: actual multimodal analysis ──
        prompt = VISION_WITH_IMAGES_PROMPT.format(
            claimed_object=claimed_object,
            claimed_part=claimed_part,
            user_claim_text=user_claim_text,
            num_images=len(images),
        )
        return analyze_images_structured(
            images=images,
            prompt=prompt,
            response_model=VisionAnalysisOutput,
            conversation=user_claim_text,
        )
    else:
        # ── Text Mode: LLM reasons from claim text only ──
        return call_structured_llm(
            prompt_template=VISION_ANALYSIS_PROMPT,
            variables={
                "image_paths": image_paths_str,
                "claimed_object": claimed_object,
                "claimed_part": claimed_part,
                "user_claim_text": user_claim_text,
            },
            response_model=VisionAnalysisOutput,
        )
