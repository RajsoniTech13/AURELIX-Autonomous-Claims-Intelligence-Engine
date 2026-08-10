"""
Deterministic image-quality gate. No LLM call, runs in preflight.

**Why this exists.** The first full benchmark run scored 2/4 on the `poor_image`
category. The cause was not that the model failed to see the problem — it was that
the model was *asked* whether the image was good enough, answered "yes", and the rule
engine believed it. A model that has already committed to a damage finding is the
worst possible judge of whether it could see well enough to make that finding.

So the measurement moves out of the model. Blur is the variance of the Laplacian;
exposure is mean luminance guarded by percentile checks. Both are cheap, both are
reproducible, and neither has an opinion about the claim.

**Override direction is one-way.** `merge_quality` takes the *worse* of the model's
assessment and the measured one — it never upgrades. The gate can see things the model
cannot (defocus, underexposure), but the model can also see things the gate cannot
(a finger over the lens, a screenshot of a photo, the wrong object entirely). Letting a
sharp, well-exposed photograph of somebody's cat be promoted to "good" because the
optics were fine would be a regression, not a fix.

**What this gate does not catch.** Occlusion, and low-resolution images that were
upscaled with a nearest-neighbour filter — the blocky edges of that particular artifact
read as *sharp* to every frequency-domain measure. See `docs/PHASE_4.1_REPORT.md`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np
import yaml
from PIL import Image

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "image_quality.yaml"

# Ordered worst-to-best. Comparisons between bands go through this, never through
# string ordering.
QUALITY_RANK: Dict[str, int] = {"unusable": 0, "poor": 1, "fair": 2, "good": 3}


@lru_cache(maxsize=1)
def load_quality_config(path: str | None = None) -> Dict[str, Any]:
    """Load image_quality.yaml. `AURELIX_IMAGE_QUALITY_CONFIG` overrides the location."""
    cfg_path = Path(path or os.getenv("AURELIX_IMAGE_QUALITY_CONFIG") or _CONFIG_PATH)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Image-quality config not found at {cfg_path}.")
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class ImageMetrics:
    """Raw measurements for one image. Reported in full so a verdict can be audited."""
    image_id: str
    width: int
    height: int
    blur_variance: float
    mean_luminance: float
    p05_luminance: float
    p95_luminance: float
    band: str                       # good | fair | poor | unusable
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "image_id": self.image_id,
            "width": self.width,
            "height": self.height,
            "blur_variance": round(self.blur_variance, 2),
            "mean_luminance": round(self.mean_luminance, 2),
            "p05_luminance": round(self.p05_luminance, 2),
            "p95_luminance": round(self.p95_luminance, 2),
            "band": self.band,
            "issues": list(self.issues),
        }


@dataclass
class PreflightQuality:
    """A claim's measured quality: the best of its images, plus the per-image detail."""
    overall: str
    score: int
    issues: List[str] = field(default_factory=list)
    per_image: List[ImageMetrics] = field(default_factory=list)
    measured: bool = True

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "score": self.score,
            "issues": list(self.issues),
            "measured": self.measured,
            "per_image": [m.to_dict() for m in self.per_image],
        }


UNMEASURED = PreflightQuality(overall="good", score=0, issues=[], per_image=[], measured=False)
"""Sentinel for "no image could be measured". Ranked `good` so it never downgrades
anything — an absent measurement is not evidence of poor quality, and the *absence* of
usable images is already handled upstream by `no_usable_image`."""


# ─── Measurement ────────────────────────────────────────────────────────────

def measure_image(img: Image.Image, image_id: str = "img_1") -> ImageMetrics:
    """Measure one decoded image. Pure function of pixels; never raises on odd modes."""
    grey = np.asarray(img.convert("L"), dtype=np.uint8)
    height, width = grey.shape

    blur_variance = float(cv2.Laplacian(grey, cv2.CV_64F).var())
    mean_luminance = float(grey.mean())
    p05, p95 = (float(v) for v in np.percentile(grey, [5, 95]))

    cfg = load_quality_config()
    blur_cfg, exp_cfg, res_cfg = cfg["blur"], cfg["exposure"], cfg["resolution"]
    dark, bright = exp_cfg["too_dark"], exp_cfg["too_bright"]

    issues: List[str] = []
    band = "good"

    def demote(to: str, issue: str) -> None:
        nonlocal band
        if QUALITY_RANK[to] < QUALITY_RANK[band]:
            band = to
        if issue not in issues:
            issues.append(issue)

    # Blur.
    if blur_variance < blur_cfg["unusable_below"]:
        demote("unusable", "blurry")
    elif blur_variance < blur_cfg["poor_below"]:
        demote("poor", "blurry")

    # Exposure. The percentile check gates the whole branch rather than just the severe
    # band: a night photograph of a dark car under a street lamp has a low mean but real
    # highlights, and is correctly exposed. Only a frame with no highlights *anywhere* is
    # underexposed, and then the mean decides how badly.
    if p95 < dark["unusable_p95_below"]:
        if mean_luminance < dark["unusable_mean_below"]:
            demote("unusable", "too_dark")
        elif mean_luminance < dark["poor_mean_below"]:
            demote("poor", "too_dark")
    elif p05 > bright["unusable_p05_above"]:
        # Symmetric: even the shadows are blown out, so there is no tonal range left.
        if mean_luminance > bright["unusable_mean_above"]:
            demote("unusable", "too_bright")
        elif mean_luminance > bright["poor_mean_above"]:
            demote("poor", "too_bright")

    # Resolution.
    if min(width, height) < res_cfg["poor_min_side_below"]:
        demote("poor", "low_resolution")

    return ImageMetrics(
        image_id=image_id, width=width, height=height,
        blur_variance=blur_variance, mean_luminance=mean_luminance,
        p05_luminance=p05, p95_luminance=p95, band=band, issues=issues,
    )


def assess_images(images: Sequence[Image.Image], image_ids: Sequence[str]) -> PreflightQuality:
    """
    Aggregate per-image measurements into one claim-level assessment.

    **Best-of, not worst-of.** One clear photograph is enough to assess damage from, so a
    claim that also happens to include a blurred second shot has not been harmed by it.
    Taking the worst would punish claimants for uploading more evidence.
    """
    metrics = [measure_image(img, iid) for img, iid in zip(images, image_ids)]
    if not metrics:
        return UNMEASURED

    best = max(metrics, key=lambda m: QUALITY_RANK[m.band])
    scores = load_quality_config()["scores"]
    return PreflightQuality(
        overall=best.band,
        score=int(scores[best.band]),
        issues=list(best.issues),
        per_image=metrics,
        measured=True,
    )


# ─── Override ───────────────────────────────────────────────────────────────

def merge_quality(
    model_overall: Optional[str],
    model_score: Optional[int],
    model_issues: Optional[Sequence[str]],
    preflight: Optional[PreflightQuality],
) -> tuple[str, int, List[str]]:
    """
    Combine the model's self-report with the measured gate. Returns (overall, score, issues).

    One-way: the measurement can only make the assessment worse. See the module docstring.
    """
    overall = (model_overall or "unusable").strip().lower()
    if overall not in QUALITY_RANK:
        overall = "unusable"
    score = int(model_score if model_score is not None else 0)
    issues = [i for i in (model_issues or []) if i and i != "none"]

    if preflight is None or not preflight.measured:
        return overall, score, issues

    if QUALITY_RANK[preflight.overall] < QUALITY_RANK[overall]:
        overall = preflight.overall
        score = min(score, preflight.score)
    for issue in preflight.issues:
        if issue not in issues:
            issues.append(issue)

    return overall, score, issues
