"""
Image Validator — UTILITY, not an agent, no LLM call.

Runs before anything else. Checks file type, resolution, corruption.
If validation fails, the graph short-circuits to a rejected state (feedback #2).
"""
from typing import List, Optional
from PIL import Image
from agent_core.schemas.models import ImageValidatorOutput

# Accepted image formats and minimum resolution
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
MIN_RESOLUTION = (200, 200)


def run_image_validator(
    images: Optional[List[Image.Image]] = None,
    image_paths_str: str = "",
) -> ImageValidatorOutput:
    """
    Validate uploaded images for format, resolution, and corruption.
    Pure Python — zero LLM calls.
    """
    issues: List[str] = []
    accepted: List[str] = []

    # Determine expected file count from paths string
    paths = [p.strip() for p in image_paths_str.split(";") if p.strip()] if image_paths_str else []

    # No images at all
    if not images or len(images) == 0:
        if paths:
            # Paths declared but no PIL images provided — text-mode fallback
            # This is valid for CLI batch processing where images are just path strings
            return ImageValidatorOutput(
                valid=True,
                file_count=len(paths),
                accepted_files=[p.split("/")[-1] for p in paths],
                issues=[],
            )
        else:
            return ImageValidatorOutput(
                valid=False,
                file_count=0,
                accepted_files=[],
                issues=["empty_upload"],
            )

    # Validate each image
    for idx, img in enumerate(images):
        file_label = f"img_{idx}"

        # Check format
        fmt = getattr(img, "format", None) or "UNKNOWN"
        if fmt.upper() not in ACCEPTED_FORMATS:
            issues.append(f"unsupported_format:{file_label}:{fmt}")
            continue

        # Check resolution
        width, height = img.size
        if width < MIN_RESOLUTION[0] or height < MIN_RESOLUTION[1]:
            issues.append(f"too_low_resolution:{file_label}:{width}x{height}")
            continue

        # If we got here, the image passed
        accepted.append(file_label)

    valid = len(accepted) > 0 and len(issues) == 0
    return ImageValidatorOutput(
        valid=valid,
        file_count=len(images),
        accepted_files=accepted,
        issues=issues,
    )
