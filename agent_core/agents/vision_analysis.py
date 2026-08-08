"""
Vision Analysis Agent — the one expensive call.

Detects damage from images. Never assesses fraud, never estimates repair cost, never
rejects a claim.

**Text-only inference is not a fallback, it is a policy decision.** When no image can be
loaded, this agent does not guess. It returns an explicit "cannot assess" finding
(`severity=unknown`, `issue_type=unknown`, `claimed_part_visible=False`) which routes the
claim to `not_enough_information`. Guessing is available only behind
`evidence.allow_text_only_inference`, is off by default, and marks its own output as
unreliable when used.

This matters because it is where the old pipeline went wrong: with `images/` absent from
the repository, every claim silently took the text-only path and Gemini was asked to
determine severity and impact direction from a *file path*. The results looked like
findings and were graded like findings.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from PIL import Image

from agent_core.prompts.templates import (
    VISION_ANALYSIS_TEXT_ONLY_PROMPT,
    VISION_ANALYSIS_WITH_IMAGES_PROMPT,
    wrap_untrusted,
)
from agent_core.schemas.models import VisionAnalysisOutput
from agent_core.services.config import evidence_config
from agent_core.services.gemini_client import (
    call_gemini_text,
    call_gemini_vision,
    compute_cache_key,
    hash_image_bytes,
)

logger = logging.getLogger("aurelix.vision")


def cannot_assess(reason: str) -> VisionAnalysisOutput:
    """
    The honest 'no usable evidence' finding.

    `unknown` rather than `none`: we are not asserting the object is undamaged, we are
    asserting we could not look. Downstream that becomes not_enough_information, never
    contradicted.
    """
    return VisionAnalysisOutput(
        status="error",
        summary="No usable image evidence was available for analysis.",
        confidence=0,
        damage_detected=False,
        object_part="unknown",
        issue_type="unknown",
        severity="unknown",
        impact_direction="unknown",
        drivable_status=True,
        claimed_part_visible=False,
        supporting_image_ids=[],
        justification=(
            f"Visual assessment was not performed because {reason} "
            f"No damage finding is asserted either way."
        ),
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
    Analyse claim images for damage.

    Raises `LLMUnavailableError` if the model cannot be reached — the caller decides what
    an absent answer means. Returns `cannot_assess(...)` when there is simply nothing to
    look at, which is a finding rather than a failure.
    """
    if images:
        prompt = VISION_ANALYSIS_WITH_IMAGES_PROMPT.format(
            claimed_object=claimed_object,
            claimed_part=claimed_part,
            num_images=len(images),
            claim_text_block=wrap_untrusted(user_claim_text),
        )
        cache_key = compute_cache_key(
            agent_name="vision_analysis",
            user_id=user_id,
            claim_text=user_claim_text,
            image_bytes_hash=hash_image_bytes(images),
        )
        return call_gemini_vision(
            images=images,
            prompt=prompt,
            response_model=VisionAnalysisOutput,
            cache_key=cache_key,
        )

    if not evidence_config()["allow_text_only_inference"]:
        return cannot_assess(
            "no readable image was supplied with the claim, and inferring damage from "
            "claim text alone is disabled by policy (evidence.allow_text_only_inference)."
        )

    # Opt-in degraded mode. The prompt forbids inventing specifics, and the result is
    # marked low-confidence so it cannot masquerade as a grounded visual finding.
    logger.warning(
        "[Vision] Text-only inference is ENABLED; findings for user=%s are not grounded in pixels.",
        user_id,
    )
    result = call_gemini_text(
        prompt=VISION_ANALYSIS_TEXT_ONLY_PROMPT.format(
            claimed_object=claimed_object,
            claimed_part=claimed_part,
            claim_text_block=wrap_untrusted(user_claim_text),
        ),
        response_model=VisionAnalysisOutput,
        cache_key=compute_cache_key(
            agent_name="vision_analysis_text_only",
            user_id=user_id,
            claim_text=user_claim_text,
            image_bytes_hash="no_images",
        ),
    )
    result.claimed_part_visible = False
    result.supporting_image_ids = []
    result.confidence = min(result.confidence, 30)
    result.justification = (
        "[UNGROUNDED — no image evidence was analysed] " + result.justification
    )
    return result
