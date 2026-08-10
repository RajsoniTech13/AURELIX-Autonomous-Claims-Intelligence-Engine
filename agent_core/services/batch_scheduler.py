"""
Adaptive batch scheduler.

Groups claims into requests under two independent budgets: claims-per-request (bounded by
cross-claim isolation risk) and images-per-request (bounded by payload size).

Sizing note that shaped this design: **image token cost is flat with respect to
resolution** — measured, 64px and 2048px both cost 1089 tokens on gemini-3.6-flash. So the
payload budget must count images, not bytes or pixels. Downscaling is still worth doing for
upload latency, but it buys no batching headroom.

A claim whose own image count exceeds the per-request image budget is sent alone rather than
being silently truncated: dropping evidence to fit a batch would be trading accuracy for
quota, which is the wrong direction here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from agent_core.agents.perception import PreparedClaim
from agent_core.services.config import batching_config

logger = logging.getLogger("aurelix.scheduler")


@dataclass
class Batch:
    batch_id: str
    claims: List[PreparedClaim] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return sum(c.image_count for c in self.claims)

    @property
    def claim_ids(self) -> List[str]:
        return [c.claim_id for c in self.claims]

    def __len__(self) -> int:
        return len(self.claims)


def plan_batches(
    claims: Sequence[PreparedClaim],
    max_claims: int | None = None,
    max_images: int | None = None,
) -> List[Batch]:
    """
    Group claims into batches. Order is preserved so runs are reproducible.

    A claim is added to the current batch while both budgets allow. Oversized claims form
    their own batch.
    """
    cfg = batching_config()
    max_claims = max_claims or cfg["max_claims_per_request"]
    max_images = max_images or cfg["max_images_per_request"]

    batches: List[Batch] = []
    current = Batch(batch_id="batch_001")

    def seal() -> None:
        nonlocal current
        if current.claims:
            batches.append(current)
            current = Batch(batch_id=f"batch_{len(batches) + 1:03d}")

    for claim in claims:
        # A single claim bigger than the whole image budget goes alone; we never drop its
        # evidence to make it fit.
        if claim.image_count >= max_images:
            seal()
            solo = Batch(batch_id=f"batch_{len(batches) + 1:03d}", claims=[claim])
            batches.append(solo)
            current = Batch(batch_id=f"batch_{len(batches) + 1:03d}")
            logger.info(
                "[Scheduler] %s sent alone (%d images >= budget %d)",
                claim.claim_id, claim.image_count, max_images,
            )
            continue

        would_exceed_claims = len(current) + 1 > max_claims
        would_exceed_images = current.image_count + claim.image_count > max_images
        if current.claims and (would_exceed_claims or would_exceed_images):
            seal()

        current.claims.append(claim)

    seal()
    return batches


def describe_plan(batches: Iterable[Batch]) -> str:
    batches = list(batches)
    total_claims = sum(len(b) for b in batches)
    total_images = sum(b.image_count for b in batches)
    return (
        f"{total_claims} claims / {total_images} images -> {len(batches)} request(s) "
        f"(avg {total_claims / max(len(batches), 1):.1f} claims per request)"
    )


def affordable_batches(batches: Sequence[Batch], remaining_requests: int) -> tuple[list[Batch], list[Batch]]:
    """
    Split a plan into what today's budget can pay for and what must wait.

    Keeps `daily_request_reserve` unspent so a retry or an isolation re-run has somewhere
    to go rather than failing the last batch of the day.
    """
    reserve = batching_config()["daily_request_reserve"]
    affordable = max(0, remaining_requests - reserve)
    return list(batches[:affordable]), list(batches[affordable:])
