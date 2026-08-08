"""
Image Validator — deterministic pre-flight. No LLM call.

This runs before anything expensive, and it is the cheapest accuracy control in the
system: if there is no usable evidence, we should say so rather than spend four LLM
calls inferring damage from a filename.

The rule it enforces: **a declared image path is not evidence.** The previous version,
when handed paths but no decoded images, returned `valid=True, file_count=len(paths)`
and called it a "text-mode fallback". Every downstream agent then treated the claim as
fully evidenced. Since `images/` does not exist in this repository, that path was taken
for all 44 claims, and the vision agent invented per-part damage findings for photographs
that were never supplied.
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence

from PIL import Image

from agent_core.schemas.contract import image_id
from agent_core.schemas.models import ImageValidatorOutput

ACCEPTED_FORMATS = {"JPEG", "JPG", "PNG", "WEBP", "MPO"}
MIN_RESOLUTION = (200, 200)

# Raw diagnostic issue -> frozen risk_flags vocabulary.
_ISSUE_TO_RISK_FLAG = {
    "missing_file": "damage_not_visible",
    "unreadable_file": "damage_not_visible",
    "empty_upload": "damage_not_visible",
    "no_images_supplied": "damage_not_visible",
    "unsupported_format": "possible_manipulation",
    "too_low_resolution": "blurry_image",
}


def _risk_flags_for(issues: Sequence[str]) -> List[str]:
    """Map `kind:img_1:detail` diagnostics onto the frozen vocabulary, de-duplicated."""
    flags = {
        _ISSUE_TO_RISK_FLAG[kind]
        for issue in issues
        if (kind := issue.split(":", 1)[0]) in _ISSUE_TO_RISK_FLAG
    }
    return sorted(flags)


def _parse_paths(image_paths_str: str) -> List[str]:
    if not image_paths_str:
        return []
    return [p.strip() for p in image_paths_str.split(";") if p.strip() and p.strip() != "none"]


def run_image_validator(
    images: Optional[List[Image.Image]] = None,
    image_paths_str: str = "",
    base_dir: Optional[str] = None,
) -> ImageValidatorOutput:
    """
    Validate submitted images for existence, format, resolution, and decodability.

    Two supply modes:
      * decoded `images` (the web upload path) — validated directly;
      * `image_paths_str` only (the CSV batch path) — resolved against `base_dir` and
        loaded from disk. Paths that do not resolve are reported as `missing_file`.

    Never raises. Callers branch on `.valid`.
    """
    paths = _parse_paths(image_paths_str)

    # ── Mode 1: decoded images supplied directly ──
    if images:
        issues: List[str] = []
        accepted: List[str] = []
        for idx, img in enumerate(images):
            label = image_id(idx)
            fmt = (getattr(img, "format", None) or "UNKNOWN").upper()
            if fmt not in ACCEPTED_FORMATS:
                issues.append(f"unsupported_format:{label}:{fmt}")
                continue
            width, height = img.size
            if width < MIN_RESOLUTION[0] or height < MIN_RESOLUTION[1]:
                issues.append(f"too_low_resolution:{label}:{width}x{height}")
                continue
            accepted.append(label)

        return ImageValidatorOutput(
            valid=bool(accepted),
            file_count=len(images),
            accepted_files=accepted,
            issues=issues,
            risk_flags=_risk_flags_for(issues),
            images_supplied=True,
        )

    # ── Mode 2: nothing declared at all ──
    if not paths:
        issues = ["empty_upload"]
        return ImageValidatorOutput(
            valid=False,
            file_count=0,
            accepted_files=[],
            issues=issues,
            risk_flags=_risk_flags_for(issues),
            images_supplied=False,
        )

    # ── Mode 3: paths declared, resolve them against the filesystem ──
    issues = []
    accepted = []
    for idx, rel_path in enumerate(paths):
        label = image_id(idx)
        candidate = rel_path if os.path.isabs(rel_path) else os.path.join(base_dir or "", rel_path)

        if not os.path.exists(candidate):
            issues.append(f"missing_file:{label}:{rel_path}")
            continue
        try:
            with Image.open(candidate) as img:
                img.verify()
            with Image.open(candidate) as img:
                fmt = (img.format or "UNKNOWN").upper()
                width, height = img.size
        except Exception as e:  # noqa: BLE001 - any decode failure means unusable evidence
            issues.append(f"unreadable_file:{label}:{type(e).__name__}")
            continue

        if fmt not in ACCEPTED_FORMATS:
            issues.append(f"unsupported_format:{label}:{fmt}")
            continue
        if width < MIN_RESOLUTION[0] or height < MIN_RESOLUTION[1]:
            issues.append(f"too_low_resolution:{label}:{width}x{height}")
            continue
        accepted.append(label)

    return ImageValidatorOutput(
        valid=bool(accepted),
        file_count=len(paths),
        accepted_files=accepted,
        issues=issues,
        risk_flags=_risk_flags_for(issues),
        images_supplied=False,
    )


def load_valid_images(
    image_paths_str: str,
    base_dir: Optional[str] = None,
    max_images: int = 6,
) -> List[Image.Image]:
    """
    Load decodable images from disk, capped at `max_images`.

    Returns only what genuinely loaded — a short list here is the signal that evidence is
    thin, and it must not be padded.
    """
    loaded: List[Image.Image] = []
    for rel_path in _parse_paths(image_paths_str):
        if len(loaded) >= max_images:
            break
        candidate = rel_path if os.path.isabs(rel_path) else os.path.join(base_dir or "", rel_path)
        if not os.path.exists(candidate):
            continue
        try:
            img = Image.open(candidate)
            img.load()
            loaded.append(img)
        except Exception:  # noqa: BLE001
            continue
    return loaded
