"""
Image Quality Agent — assesses quality and usability of claim evidence images.
Dual-mode:
  - Vision mode: receives PIL images → Gemini Vision quality check
  - Text mode:  no images → LLM reasons from claim text context only
"""
from typing import List, Optional
from PIL import Image

from agent_core.services.llm import call_structured_llm
from agent_core.services.vision_llm import analyze_images_structured
from agent_core.schemas.models import ImageQualityOutput
from agent_core.prompts.templates import (
    IMAGE_QUALITY_PROMPT,
    IMAGE_QUALITY_WITH_IMAGES_PROMPT,
)


def run_image_quality_agent(
    claimed_object: str,
    claimed_part: str,
    conversation: str,
    images: Optional[List[Image.Image]] = None,
    image_paths_str: str = "",
) -> ImageQualityOutput:
    """
    Assess image quality for claim evidence.

    If `images` (PIL objects) are provided, uses Gemini Vision for real quality analysis.
    Otherwise, uses text-only LLM reasoning based on claim context.
    """
    if images and len(images) > 0:
        # ── Vision Mode: actual image quality check ──
        prompt = IMAGE_QUALITY_WITH_IMAGES_PROMPT.format(
            claimed_object=claimed_object,
            claimed_part=claimed_part,
            conversation=conversation,
            num_images=len(images),
        )
        return analyze_images_structured(
            images=images,
            prompt=prompt,
            response_model=ImageQualityOutput,
            conversation=conversation,
        )
    else:
        # ── Text Mode: LLM reasons from claim text only ──
        return call_structured_llm(
            prompt_template=IMAGE_QUALITY_PROMPT,
            variables={
                "image_paths": image_paths_str,
                "claimed_object": claimed_object,
                "claimed_part": claimed_part,
                "conversation": conversation,
            },
            response_model=ImageQualityOutput,
        )
