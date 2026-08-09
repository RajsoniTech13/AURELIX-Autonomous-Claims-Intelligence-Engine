"""
Perceptual hashing for submitted photographs.

**Why this is the fraud feature that matters.** In damage claims the single strongest
objective fraud signal is not a suspicious narrative — it is a photograph that has already
been submitted, under a different claim or by a different claimant. Everything else in the
fraud score is inference. This is a fact.

`R030_duplicate_image_reuse` has existed in `config/decision_rules.yaml` since Phase 2 and
has never been able to fire, because nothing indexed an image. This module is the missing
half.

**Why hashes and not embeddings.** A cryptographic hash changes completely when a single
byte does, so re-saving a JPEG at a different quality defeats it entirely. A perceptual hash
is computed from image *structure*, so it survives re-encoding, resizing, mild brightness
changes and light cropping — which is exactly the set of transformations a claimant applies,
usually without meaning to, by sending the photo through a messaging app.

Two independent hashes are computed because they fail differently: pHash is a frequency-domain
signature and is robust to gamma and scaling; dHash is a gradient signature and is better at
distinguishing images that share global structure but differ locally. Requiring agreement
between them is what keeps the false-positive rate at zero on the evaluation set — and a
false positive here accuses somebody of fraud, so the asymmetry is deliberate.

No neural model, no network, no quota. See `docs/PHASE_4.4_REPORT.md` for the measured
precision/recall and for what a semantic image embedding would add on top.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Sequence

import numpy as np
from PIL import Image

HASH_BITS = 64
_PHASH_SIZE = 32          # image is reduced to 32x32 before the DCT
_PHASH_KEEP = 8           # top-left 8x8 of the DCT holds the low frequencies


@lru_cache(maxsize=4)
def _dct_matrix(n: int) -> np.ndarray:
    """
    Orthonormal DCT-II basis, so a 2D DCT is `D @ img @ D.T`.

    Built here rather than pulled from scipy: it is six lines, it removes a heavy
    dependency from the runtime image, and it is exactly reproducible.
    """
    k = np.arange(n).reshape(-1, 1)
    i = np.arange(n).reshape(1, -1)
    basis = np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    basis[0] *= np.sqrt(1 / n)
    basis[1:] *= np.sqrt(2 / n)
    return basis


def _grey(img: Image.Image, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(img.convert("L").resize(size, Image.LANCZOS), dtype=np.float64)


def phash(img: Image.Image) -> int:
    """
    64-bit DCT perceptual hash.

    The DC coefficient is excluded from the median: it encodes overall brightness, so
    including it would let a simple exposure shift flip a large share of the bits.
    """
    dct = _dct_matrix(_PHASH_SIZE)
    coeffs = dct @ _grey(img, (_PHASH_SIZE, _PHASH_SIZE)) @ dct.T
    low = coeffs[:_PHASH_KEEP, :_PHASH_KEEP].flatten()
    median = np.median(low[1:])
    bits = low > median
    return _bits_to_int(bits)


def dhash(img: Image.Image) -> int:
    """64-bit horizontal-gradient hash: each bit is 'is this pixel brighter than its right neighbour'."""
    grey = _grey(img, (9, 8))
    return _bits_to_int((grey[:, :-1] > grey[:, 1:]).flatten())


def _bits_to_int(bits: Sequence[bool] | np.ndarray) -> int:
    value = 0
    for bit in np.asarray(bits).flatten():
        value = (value << 1) | int(bool(bit))
    return value


def hamming(a: int, b: int) -> int:
    """Number of differing bits. 0 = identical structure, 64 = maximally different."""
    return int(a ^ b).bit_count()


@dataclass(frozen=True)
class ImageFingerprint:
    """Everything we retain about a photograph. Never the photograph itself."""
    phash: int
    dhash: int
    width: int
    height: int

    def to_dict(self) -> dict:
        # Hex, because SQLite integers are signed 64-bit and a hash with the top bit set
        # would round-trip as a negative number.
        return {"phash": f"{self.phash:016x}", "dhash": f"{self.dhash:016x}",
                "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, d: dict) -> "ImageFingerprint":
        return cls(phash=int(d["phash"], 16), dhash=int(d["dhash"], 16),
                   width=int(d.get("width", 0)), height=int(d.get("height", 0)))


def fingerprint(img: Image.Image) -> ImageFingerprint:
    return ImageFingerprint(
        phash=phash(img), dhash=dhash(img), width=img.width, height=img.height,
    )


def fingerprint_all(images: Sequence[Image.Image]) -> List[ImageFingerprint]:
    return [fingerprint(img) for img in images]
