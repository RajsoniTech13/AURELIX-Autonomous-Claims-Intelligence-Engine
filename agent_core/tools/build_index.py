"""
Offline index build.

Run: `python -m agent_core.tools.build_index`

Two indexes, built once and loaded at process start rather than rebuilt per claim — which
is what `services/vector_store.py` did, re-deriving its whole vocabulary and IDF table
inside every `search()` call.

* **Image index** — perceptual fingerprints of every historical photograph, so a new claim
  can be checked against everything already submitted. This is what makes
  `R030_duplicate_image_reuse` able to fire.
* **Text index** — historical claims for hybrid retrieval, fused dense + BM25.

Only images the Phase 4.1 quality gate accepts are indexed. A near-featureless image has an
unstable perceptual hash (measured: 22 bits of drift under nothing worse than a JPEG
re-encode), so indexing one manufactures false accusations later.

No model is called. This costs nothing.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

from PIL import Image

from agent_core.agents.image_quality import measure_image
from agent_core.retrieval.hybrid import Document, HybridRetriever
from agent_core.retrieval.image_index import ImageIndex, IndexedImage, content_hash, indexable
from agent_core.retrieval.hashing import fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLAIMS = REPO_ROOT / "agent_core" / "data" / "synthetic" / "claims_synthetic.csv"
DEFAULT_TEXT_INDEX = REPO_ROOT / ".aurelix" / "text_index.json"


def _parse_paths(value: str) -> List[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip() and p.strip() != "none"]


def build_image_index(
    rows: List[Dict[str, str]], image_root: Path, index: ImageIndex, verbose: bool = True,
) -> Dict[str, int]:
    indexed = skipped = missing = 0
    for row in rows:
        claim_id = row.get("claim_id") or row.get("user_id", "")
        user_id = row.get("user_id", "")
        entries = []
        for position, rel in enumerate(_parse_paths(row.get("image_paths", "")), start=1):
            path = Path(rel) if Path(rel).is_absolute() else image_root / rel
            if not path.exists():
                missing += 1
                continue
            try:
                img = Image.open(path).convert("RGB")
            except Exception:  # noqa: BLE001 - an undecodable file is simply not evidence
                missing += 1
                continue

            band = measure_image(img).band
            if not indexable(band):
                # Not a failure. An image we would refuse to analyse is an image whose
                # fingerprint we should not trust either.
                skipped += 1
                if verbose:
                    print(f"  skip {claim_id} img_{position}: quality {band}")
                continue

            entries.append(IndexedImage(
                claim_id=claim_id, user_id=user_id, image_id=f"img_{position}",
                fingerprint=fingerprint(img), content=content_hash(img),
            ))
        indexed += index.add(entries)

    return {"indexed": indexed, "skipped_low_quality": skipped, "missing": missing}


def build_text_index(rows: List[Dict[str, str]], out_path: Path) -> int:
    """
    Persist the retrieval corpus. Vectors are not persisted — an SVD over a few thousand
    short documents rebuilds in milliseconds, and a stored projection matrix would be one
    more artefact able to drift out of step with the corpus it describes.
    """
    documents = [
        Document(
            doc_id=row.get("claim_id") or row.get("user_id", ""),
            text=row.get("user_claim", ""),
            metadata={
                "object_category": (row.get("claim_object") or "").lower(),
                "user_id": row.get("user_id", ""),
            },
        )
        for row in rows
    ]
    HybridRetriever().index(documents)      # fail here rather than at first query
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        [{"doc_id": d.doc_id, "text": d.text, "metadata": d.metadata} for d in documents],
        indent=1,
    ), encoding="utf-8")
    return len(documents)


def load_text_index(path: Path | str = DEFAULT_TEXT_INDEX) -> HybridRetriever:
    path = Path(path)
    if not path.exists():
        return HybridRetriever().index([])
    raw = json.loads(path.read_text(encoding="utf-8"))
    return HybridRetriever().index([
        Document(doc_id=d["doc_id"], text=d["text"], metadata=d.get("metadata", {}))
        for d in raw
    ])


def main() -> int:
    p = argparse.ArgumentParser(description="Build the AURELIX retrieval indexes (no API calls)")
    p.add_argument("--claims", default=str(DEFAULT_CLAIMS))
    p.add_argument("--image-root", default=str(REPO_ROOT))
    p.add_argument("--image-index", default=None, help="SQLite path (default: .aurelix/image_index.db)")
    p.add_argument("--text-index", default=str(DEFAULT_TEXT_INDEX))
    p.add_argument("--fresh", action="store_true", help="Clear the image index before building")
    args = p.parse_args()

    claims_path = Path(args.claims)
    if not claims_path.exists():
        print(f"Error: claims file not found: {claims_path}", file=sys.stderr)
        return 1

    with claims_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"=== AURELIX index build === ({len(rows)} claims from {claims_path.name})")

    index = ImageIndex(args.image_index)
    if args.fresh:
        index.clear()
        print("Image index cleared.")

    stats = build_image_index(rows, Path(args.image_root), index)
    print(f"Image index : {stats['indexed']} fingerprints "
          f"({stats['skipped_low_quality']} skipped on quality, {stats['missing']} unreadable) "
          f"-> {index.path}  [{index.count()} total]")

    count = build_text_index(rows, Path(args.text_index))
    print(f"Text index  : {count} documents -> {args.text_index}")
    print("No API calls were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
