"""
Batched multimodal perception — the only LLM call in the system.

Replaces four separate per-claim calls (claim_ingestion, vision_analysis, fraud_review,
decision) with one request covering several claims. For 44 claims at 3 per request that is
15 requests instead of 176, which is what makes the benchmark fit inside the free tier.

The interesting engineering here is not the batching, it is the **isolation checking**. The
prompt asks the model to keep claims separate; this module verifies that it did, and refuses
results it cannot vouch for.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image

from agent_core.prompts.batch_perception import (
    BATCH_SYSTEM_PROMPT,
    CLAIM_BLOCK_FOOTER,
    IMAGE_LABEL,
    build_batch_instruction,
    build_claim_block_header,
)
from agent_core.schemas.contract import image_id
from agent_core.schemas.perception import BatchPerceptionOutput, ClaimPerception
from agent_core.services.gemini_client import (
    LLMUnavailableError,
    call_gemini_multimodal,
    compute_cache_key,
    hash_image_bytes,
)

logger = logging.getLogger("aurelix.perception")


class BatchIsolationError(RuntimeError):
    """
    The response could not be shown to respect claim boundaries.

    Deliberately fatal for the batch. A result we cannot vouch for is worse than no result:
    a contaminated verdict looks exactly like a good one on the way out.
    """


class PreparedClaim:
    """One claim staged for a batch: its text plus its own decoded images."""

    __slots__ = ("claim_id", "claim_object", "claim_text", "images", "raw")

    def __init__(self, claim_id: str, claim_object: str, claim_text: str,
                 images: Sequence[Image.Image], raw: Dict[str, Any] | None = None):
        self.claim_id = claim_id
        self.claim_object = claim_object
        self.claim_text = claim_text
        self.images = list(images)
        self.raw = raw or {}

    @property
    def image_count(self) -> int:
        return len(self.images)

    def image_ids(self) -> List[str]:
        return [image_id(i) for i in range(len(self.images))]


def build_batch_contents(claims: Sequence[PreparedClaim]) -> List[Any]:
    """
    Interleave text and images so every image is structurally adjacent to a label naming
    its owning claim. Ordering is what the model has to rely on, so it must be unambiguous.
    """
    contents: List[Any] = [BATCH_SYSTEM_PROMPT]

    for claim in claims:
        contents.append(build_claim_block_header(
            claim.claim_id, claim.claim_object, claim.claim_text,
        ))
        if not claim.images:
            contents.append(f"(no images were submitted with {claim.claim_id})\n")
        for idx, img in enumerate(claim.images):
            contents.append(IMAGE_LABEL.format(claim_id=claim.claim_id, image_id=image_id(idx)))
            contents.append(img)
        contents.append(CLAIM_BLOCK_FOOTER.format(claim_id=claim.claim_id) + "\n")

    contents.append(build_batch_instruction([c.claim_id for c in claims]))
    return contents


def validate_isolation(
    response: BatchPerceptionOutput,
    claims: Sequence[PreparedClaim],
) -> Dict[str, ClaimPerception]:
    """
    Verify the response respects claim boundaries. Raises `BatchIsolationError` otherwise.

    Checks, in order of how badly each would corrupt a verdict:
      1. every requested claim_id present, exactly once
      2. no claim_id we did not ask for
      3. no image id outside that claim's own range  <- the actual contamination signature
    """
    requested = [c.claim_id for c in claims]
    requested_set = set(requested)

    seen: Dict[str, ClaimPerception] = {}
    duplicates: List[str] = []
    unexpected: List[str] = []

    for result in response.results:
        cid = (result.claim_id or "").strip()
        if cid not in requested_set:
            unexpected.append(cid)
            continue
        if cid in seen:
            duplicates.append(cid)
            continue
        seen[cid] = result

    missing = [cid for cid in requested if cid not in seen]

    problems: List[str] = []
    if missing:
        problems.append(f"missing results for {missing}")
    if duplicates:
        problems.append(f"duplicate results for {duplicates}")
    if unexpected:
        problems.append(f"results for claim ids never sent: {unexpected}")

    # Cross-claim image references. If claim A cites img_4 but only supplied two images,
    # the model was either guessing or looking at someone else's evidence.
    by_id = {c.claim_id: c for c in claims}
    for cid, result in seen.items():
        valid_ids = set(by_id[cid].image_ids())
        cited = set(result.supporting_image_ids or [])
        cited |= {d.image_id for d in result.damage_analysis.damaged_parts if d.image_id}
        stray = {i for i in cited if i and i not in valid_ids}
        if stray:
            problems.append(
                f"{cid} cited image ids {sorted(stray)} but only owns {sorted(valid_ids) or '[]'}"
            )

    if problems:
        raise BatchIsolationError("; ".join(problems))

    return seen


def run_batch_perception(
    claims: Sequence[PreparedClaim],
    model: Optional[str] = None,
    use_cache: bool = True,
) -> Dict[str, ClaimPerception]:
    """
    One multimodal request for the whole batch. Returns `{claim_id: ClaimPerception}`.

    Raises `LLMUnavailableError` if the model could not be reached, or
    `BatchIsolationError` if the response failed the boundary checks. Callers must treat
    both as "no result for these claims", never as a verdict.
    """
    if not claims:
        return {}

    contents = build_batch_contents(claims)

    cache_key = None
    if use_cache:
        # Keyed over every claim in the batch, so a re-run with the same grouping is free
        # and a different grouping is a genuine miss.
        fingerprint = "|".join(
            f"{c.claim_id}:{hash_image_bytes(c.images)}:{hash(c.claim_text.strip())}"
            for c in claims
        )
        cache_key = compute_cache_key(agent_name="batch_perception", claim_text=fingerprint)

    logger.info(
        "[Perception] batch of %d claims, %d images total",
        len(claims), sum(c.image_count for c in claims),
    )

    response = call_gemini_multimodal(
        contents=contents,
        response_model=BatchPerceptionOutput,
        model=model,
        cache_key=cache_key,
        description=f"BatchPerception({len(claims)} claims)",
    )

    return validate_isolation(response, claims)
