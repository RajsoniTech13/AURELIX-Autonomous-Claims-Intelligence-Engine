"""
The image index that makes `R030_duplicate_image_reuse` able to fire.

The rule has been in `config/decision_rules.yaml` since Phase 2 with nothing capable of
setting its condition — the strongest fraud signal in the domain, declared and dead. This
module is the missing half: every photograph that passes the quality gate is fingerprinted
and stored, and every new claim is checked against everything already there.

**What is stored is not the photograph.** Two 64-bit perceptual hashes and a content hash.
That is a deliberate privacy property: the index can say "this image was submitted before,
under claim X" without retaining anybody's photograph, and a leak of the index leaks no
images.

**Two tiers, because they are not the same evidence.** An identical-bytes match is a fact
with no threshold attached. A perceptual match is a judgement with a distance behind it, and
it is reported with that distance so a reviewer can weigh it. Both set
`duplicate_image_reuse`; the tier and distances travel with the match so the audit trail
records *why*.

**Scale.** The query is a linear scan with a popcount per candidate — microseconds for the
tens of thousands of images this will hold, and honest about it. Production scale wants a
BK-tree or multi-index LSH over the hash space; the interface here does not change when
that arrives.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml
from PIL import Image

from agent_core.retrieval.hashing import ImageFingerprint, fingerprint, hamming

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "retrieval.yaml"
DEFAULT_INDEX_PATH = ".aurelix/image_index.db"


@lru_cache(maxsize=1)
def load_retrieval_config(path: str | None = None) -> Dict[str, Any]:
    cfg_path = Path(path or os.getenv("AURELIX_RETRIEVAL_CONFIG") or _CONFIG_PATH)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Retrieval config not found at {cfg_path}.")
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def content_hash(img: Image.Image) -> str:
    """
    SHA-256 over the decoded pixels, not the file bytes.

    Deliberate: re-saving an unmodified image changes the file (different encoder, EXIF
    stripped, different quantisation tables) while the pixels are identical. Hashing pixels
    means "the same photograph" stays exact-tier rather than degrading to a judgement call.
    """
    rgb = img.convert("RGB")
    return hashlib.sha256(rgb.tobytes() + f"|{rgb.width}x{rgb.height}".encode()).hexdigest()


@dataclass(frozen=True)
class DuplicateMatch:
    """One prior submission of the same photograph."""
    image_id: str            # id within the claim being checked, e.g. img_1
    prior_claim_id: str
    prior_user_id: str
    prior_image_id: str
    kind: str                # "exact" | "near"
    phash_distance: int
    dhash_distance: int

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        if self.kind == "exact":
            return (f"{self.image_id} is byte-identical to {self.prior_image_id} of claim "
                    f"{self.prior_claim_id} (claimant {self.prior_user_id}).")
        return (f"{self.image_id} matches {self.prior_image_id} of claim "
                f"{self.prior_claim_id} (claimant {self.prior_user_id}) perceptually "
                f"[pHash {self.phash_distance}, dHash {self.dhash_distance} bits apart].")


@dataclass
class IndexedImage:
    claim_id: str
    user_id: str
    image_id: str
    fingerprint: ImageFingerprint
    content: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS indexed_images (
    claim_id     TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    image_id     TEXT NOT NULL,
    phash        TEXT NOT NULL,
    dhash        TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    width        INTEGER,
    height       INTEGER,
    PRIMARY KEY (claim_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_content ON indexed_images(content_hash);
"""


class ImageIndex:
    """Persistent perceptual-hash index. Safe to construct repeatedly."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("AURELIX_IMAGE_INDEX") or DEFAULT_INDEX_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── writing ──

    def add(self, entries: Iterable[IndexedImage]) -> int:
        rows = [(e.claim_id, e.user_id, e.image_id, f"{e.fingerprint.phash:016x}",
                 f"{e.fingerprint.dhash:016x}", e.content,
                 e.fingerprint.width, e.fingerprint.height) for e in entries]
        if not rows:
            return 0
        with self._connect() as conn:
            # Replace rather than ignore: reprocessing a claim should refresh its entry,
            # not leave a stale fingerprint that a later query would match against.
            conn.executemany(
                "INSERT OR REPLACE INTO indexed_images "
                "(claim_id, user_id, image_id, phash, dhash, content_hash, width, height) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows,
            )
        return len(rows)

    def add_claim_images(
        self, claim_id: str, user_id: str, images: Sequence[Image.Image],
        image_ids: Optional[Sequence[str]] = None,
    ) -> int:
        ids = list(image_ids or [f"img_{i + 1}" for i in range(len(images))])
        return self.add([
            IndexedImage(claim_id=claim_id, user_id=user_id, image_id=iid,
                         fingerprint=fingerprint(img), content=content_hash(img))
            for img, iid in zip(images, ids)
        ])

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM indexed_images")

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM indexed_images").fetchone()[0])

    # ── querying ──

    def find_duplicates(
        self,
        images: Sequence[Image.Image],
        *,
        claim_id: str,
        user_id: str = "",
        image_ids: Optional[Sequence[str]] = None,
    ) -> List[DuplicateMatch]:
        """
        Every prior submission matching one of these images.

        Call this **before** adding the claim's own images, or every claim matches itself.
        """
        cfg = load_retrieval_config()["duplicate_detection"]
        if not cfg.get("enabled", True) or not images:
            return []

        near_cfg = cfg.get("near_duplicate", {})
        near_on = bool(near_cfg.get("enabled", True))
        max_p = int(near_cfg.get("max_phash_distance", 12))
        max_d = int(near_cfg.get("max_dhash_distance", 10))
        ignore_same_claim = bool(cfg.get("ignore_same_claim", True))

        ids = list(image_ids or [f"img_{i + 1}" for i in range(len(images))])
        probes = [(iid, fingerprint(img), content_hash(img)) for img, iid in zip(images, ids)]

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT claim_id, user_id, image_id, phash, dhash, content_hash "
                "FROM indexed_images"
            ).fetchall()

        matches: List[DuplicateMatch] = []
        for iid, fp, chash in probes:
            best: Optional[DuplicateMatch] = None
            for row in rows:
                if ignore_same_claim and row["claim_id"] == claim_id:
                    continue

                if row["content_hash"] == chash:
                    kind, pd, dd = "exact", 0, 0
                elif near_on:
                    pd = hamming(fp.phash, int(row["phash"], 16))
                    dd = hamming(fp.dhash, int(row["dhash"], 16))
                    # Both must agree. pHash and dHash fail differently, so an OR would
                    # inherit the worse failure mode of the two.
                    if pd > max_p or dd > max_d:
                        continue
                    kind = "near"
                else:
                    continue

                candidate = DuplicateMatch(
                    image_id=iid, prior_claim_id=row["claim_id"],
                    prior_user_id=row["user_id"], prior_image_id=row["image_id"],
                    kind=kind, phash_distance=pd, dhash_distance=dd,
                )
                # One match per image, and an exact match always outranks a near one.
                if best is None or (best.kind == "near" and kind == "exact") or (
                    best.kind == kind and (pd + dd) < (best.phash_distance + best.dhash_distance)
                ):
                    best = candidate
                if best.kind == "exact":
                    break

            if best is not None:
                matches.append(best)

        return matches


def indexable(quality_band: str) -> bool:
    """
    Is an image good enough to fingerprint?

    A near-featureless image has DCT coefficients bunched around the median, so its pHash
    flips wildly under a mere re-encode — measured at 22 bits on `blurred.jpg`. Indexing
    such an image would generate false accusations. The Phase 4.1 quality gate already
    identifies exactly this class, so it is reused rather than re-derived.
    """
    allowed = load_retrieval_config()["duplicate_detection"].get(
        "require_quality", ["good", "fair", "poor"])
    return quality_band in allowed
