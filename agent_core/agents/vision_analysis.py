"""
Vision Analysis Agent — Gemini Vision (the one expensive call).

Dual-mode:
  - Vision mode: receives PIL images → Gemini Vision multimodal analysis
  - Text mode:  no images → Gemini reasons from claim text + context only

Detects: damage, severity, impact direction, drivable status.
Never assesses fraud. Never estimates repair cost. Never rejects a claim.
"""
from typing import List, Optional
from PIL import Image

from agent_core.services.gemini_client import (
    call_gemini_text,
    call_gemini_vision,
    compute_cache_key,
    hash_image_bytes,
)
from agent_core.schemas.models import VisionAnalysisOutput
from agent_core.prompts.templates import (
    VISION_ANALYSIS_PROMPT,
    VISION_ANALYSIS_WITH_IMAGES_PROMPT,
)


def run_vision_analysis_agent(
    claimed_object: str,
    claimed_part: str,
    user_claim_text: str,
    user_id: str = "",
    images: Optional[List[Image.Image]] = None,
    image_paths_str: str = "",
) -> VisionAnalysisOutput:
    """
    Analyze claim images for damage.

    If `images` (PIL objects) are provided, uses Gemini Vision for pixel analysis.
    Otherwise, falls back to text-only Gemini reasoning.
    """
    img_hash = hash_image_bytes(images) if images else "no_images"

    cache_key = compute_cache_key(
        agent_name="vision_analysis",
        user_id=user_id,
        claim_text=user_claim_text,
        image_bytes_hash=img_hash,
    )

    if images and len(images) > 0:
        # ── Vision Mode: actual multimodal analysis ──
        prompt = VISION_ANALYSIS_WITH_IMAGES_PROMPT.format(
            claimed_object=claimed_object,
            claimed_part=claimed_part,
            user_claim_text=user_claim_text,
            num_images=len(images),
        )
        return call_gemini_vision(
            images=images,
            prompt=prompt,
            response_model=VisionAnalysisOutput,
            cache_key=cache_key,
        )
    else:
        # ── Text Mode: Gemini reasons from claim text only ──
        prompt = VISION_ANALYSIS_PROMPT.format(
            image_paths=image_paths_str,
            claimed_object=claimed_object,
            claimed_part=claimed_part,
            user_claim_text=user_claim_text,
        )
        return call_gemini_text(
            prompt=prompt,
            response_model=VisionAnalysisOutput,
            cache_key=cache_key,
        )
