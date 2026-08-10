"""
Accepting, hardening and persisting claim photographs.

Until now uploads were decoded into memory, analysed, and thrown away — while
`image_paths` recorded `uploads/<original filename>`, a path that resolved to nothing. The
review screen dutifully rendered `<img src=".../uploads/whatever.jpg">` for every one of
them and got a 404, so the one piece of evidence the whole verdict rests on was the one
thing a reviewer could not look at.

This module is the single front door for both submission routes. It does four things the
previous inline code in `routes.py` and `v1.py` did not:

* **Caps the request.** A file count cap and a per-file byte cap, both configurable. An
  unbounded multipart body on a 512 MB free-tier container is a denial of service that
  costs the attacker one curl.
* **Sniffs content rather than trusting it.** The stored extension comes from what Pillow
  decoded (`Image.format`), never from the client's filename or Content-Type.
* **Never uses the client's filename on disk.** Names are generated; a caller controlling
  the filename controls the path, and `../../` is the oldest trick there is.
* **Persists what it decoded**, so the stored path is one a reviewer can actually open.

Storage is the local filesystem, deliberately. On Render's free tier that disk is ephemeral
— images survive the container, not a redeploy — and saying so is better than implying
durability that is not there. The seam for S3 is `save_image()`; nothing else knows where
bytes live.
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path
from typing import List, Sequence, Tuple

from fastapi import HTTPException, UploadFile
from PIL import Image

from platform_backend.config import settings

# Pillow will happily open a 50000x50000 PNG that decompresses to gigabytes. This is the
# decompression-bomb guard; Pillow raises DecompressionBombError past it.
Image.MAX_IMAGE_PIXELS = 64_000_000  # 64 MP

# What we are willing to store and serve back. Anything Pillow decodes to something outside
# this set is rejected rather than saved under a guessed extension.
_ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}

UPLOAD_URL_PREFIX = "uploads"


def upload_dir() -> Path:
    """
    Resolved per call, not cached at import.

    `settings` is a module-level singleton, so a test that sets `UPLOAD_DIR` after import
    would otherwise still write into the real directory — and a suite that scatters fixture
    photographs through the same folder production serves from is a slow-motion accident.
    """
    d = Path(os.getenv("UPLOAD_DIR") or settings.UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_image(raw: bytes, fmt: str) -> str:
    """
    Write one decoded image and return the path recorded on the claim.

    The returned value is relative (`uploads/<uuid>.jpg`) and is what the frontend appends
    to the API base to fetch it. Absolute URLs are not stored: the API's own hostname
    differs between local, preview and production, and baking one into a database row makes
    every historical claim point at whichever environment happened to create it.
    """
    name = f"{uuid.uuid4().hex}{_ALLOWED_FORMATS.get(fmt, '.img')}"
    (upload_dir() / name).write_bytes(raw)
    return f"{UPLOAD_URL_PREFIX}/{name}"


async def read_uploads(files: Sequence[UploadFile]) -> Tuple[List[Image.Image], str]:
    """
    Validate, cap, decode and persist an upload set.

    Returns the decoded images (which is what the pipeline actually analyses) and the
    semicolon-joined stored paths for the `image_paths` column, or `"none"` when the
    submission carried no files.

    Decoding happens here, at the edge, rather than on the worker. A malformed upload then
    fails fast with a 400 the submitter can act on, instead of becoming a job that fails
    asynchronously for a reason they never see.
    """
    real = [f for f in files if f and f.filename]
    if len(real) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Too many files: {len(real)}. "
                f"At most {settings.MAX_UPLOAD_FILES} images per claim."
            ),
        )

    images: List[Image.Image] = []
    paths: List[str] = []
    for upload in real:
        raw = await upload.read()
        if len(raw) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"'{upload.filename}' is {len(raw) // 1024} KB; "
                    f"the limit is {settings.MAX_UPLOAD_BYTES // 1024} KB per image."
                ),
            )
        if not raw:
            raise HTTPException(status_code=400, detail=f"'{upload.filename}' is empty.")

        try:
            probe = Image.open(io.BytesIO(raw))
            probe.verify()                  # verify() consumes the object; reopen to use it
            fmt = (probe.format or "").upper()
            image = Image.open(io.BytesIO(raw))
            image.load()                    # force full decode: truncated files fail here
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - any decode failure is a client error, not a 500
            raise HTTPException(
                status_code=400, detail=f"'{upload.filename}' is not a readable image.",
            )

        if fmt not in _ALLOWED_FORMATS:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"'{upload.filename}' decoded as {fmt or 'unknown'}. "
                    f"Supported: {', '.join(sorted(_ALLOWED_FORMATS))}."
                ),
            )

        images.append(image)
        paths.append(save_image(raw, fmt))

    return images, ";".join(paths) if paths else "none"
