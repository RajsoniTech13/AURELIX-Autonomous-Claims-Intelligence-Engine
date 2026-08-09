"""
Offline index build.

Run: `python -m agent_core.tools.build_index`

Built once and loaded at process start rather than rebuilt per claim — which is what
`services/vector_store.py` did, re-deriving its whole vocabulary and IDF table inside every
`search()` call.

* **Image index** — perceptual fingerprints of every historical photograph, so a new claim
  can be checked against everything already submitted. This is what makes
  `R030_duplicate_image_reuse` able to fire.
* **`historical_claims`** — past claims indexed on the narrative *plus what was observed*,
  read from stored perception. Narrative alone retrieves claims that sound alike; adding the
  outcome retrieves claims that turned out alike.
* **`policy_rules`** — evidence requirements chunked one per requirement, each with a stable
  `rule_id`, so a compliance failure can cite `EV-CAR-COUNT` rather than "the car policy".
* **`fraud_patterns`** — the curated playbook, for reviewer context only.

Builds are **upserts** by default (`--fresh` to start over), so a nightly run can add new
claims without re-reading the whole history and a partial build cannot silently truncate a
collection.

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
from agent_core.retrieval.collections import (
    FRAUD_PATTERNS,
    HISTORICAL_CLAIMS,
    POLICY_RULES,
    INDEX_VERSION,
    IndexBundle,
    build_fraud_patterns,
    build_historical_claims,
    build_policy_rules,
)
from agent_core.retrieval.hybrid import HybridRetriever
from agent_core.retrieval.image_index import ImageIndex, IndexedImage, content_hash, indexable
from agent_core.retrieval.hashing import fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLAIMS = REPO_ROOT / "agent_core" / "data" / "synthetic" / "claims_synthetic.csv"
DEFAULT_INDEX_DIR = REPO_ROOT / ".aurelix" / "index"
DEFAULT_EVIDENCE_CSV = REPO_ROOT / "agent_core" / "data" / "evidence_requirements.csv"
DEFAULT_FRAUD_PATTERNS = REPO_ROOT / "agent_core" / "data" / "fraud_patterns.yaml"
DEFAULT_RESULTS = REPO_ROOT / "agent_core" / "output" / "results_detail.json"


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


def observed_outcomes(results_path: Path) -> Dict[str, Dict[str, str]]:
    """
    What was actually observed on each past claim, read from stored perception.

    Indexing the claimant's narrative alone retrieves claims that *sound* alike. Adding the
    observed part, damage type and final verdict retrieves claims that *turned out* alike,
    which is the question a reviewer is really asking. Free: this is already on disk.
    """
    if not results_path.exists():
        return {}
    outcomes: Dict[str, Dict[str, str]] = {}
    for record in json.loads(results_path.read_text(encoding="utf-8")):
        perception = record.get("perception") or {}
        parts = (perception.get("damage_analysis") or {}).get("damaged_parts") or []
        first = parts[0] if parts else {}
        outcomes[record["claim_id"]] = {
            "part": first.get("part", ""),
            "issue_type": first.get("issue_type", ""),
            "severity": first.get("severity", ""),
            "claim_status": (record.get("verdict") or {}).get("claim_status", ""),
        }
    return outcomes


def build_collections(
    rows: List[Dict[str, str]],
    *,
    index_dir: Path,
    evidence_csv: Path,
    fraud_patterns_yaml: Path,
    results_json: Path,
    fresh: bool = False,
) -> IndexBundle:
    """
    Build all three collections and persist them with a manifest.

    Loaded rather than recreated when it already exists, so a build is an **upsert**: a
    nightly run can add yesterday's claims without re-reading the whole history, and a
    partial build cannot silently truncate a collection to whatever it happened to see.
    """
    bundle = IndexBundle(directory=index_dir) if fresh else IndexBundle.load(index_dir)
    bundle.directory = index_dir

    current = {
        HISTORICAL_CLAIMS: build_historical_claims(rows, observed_outcomes(results_json)),
        POLICY_RULES: build_policy_rules(evidence_csv),
        FRAUD_PATTERNS: build_fraud_patterns(fraud_patterns_yaml),
    }
    stale = bundle.stale_collections(current)

    for name, documents in current.items():
        bundle.upsert(name, documents)
        # Constructing the retriever now means a malformed corpus fails during the build
        # rather than at the first query from a live request.
        bundle.retriever(name)

    bundle.save()
    return bundle, stale


def main() -> int:
    p = argparse.ArgumentParser(description="Build the AURELIX retrieval indexes (no API calls)")
    p.add_argument("--claims", default=str(DEFAULT_CLAIMS))
    p.add_argument("--image-root", default=str(REPO_ROOT))
    p.add_argument("--image-index", default=None, help="SQLite path (default: .aurelix/image_index.db)")
    p.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR),
                   help="Directory for the three-collection index and its manifest")
    p.add_argument("--evidence-csv", default=str(DEFAULT_EVIDENCE_CSV))
    p.add_argument("--fraud-patterns", default=str(DEFAULT_FRAUD_PATTERNS))
    p.add_argument("--results", default=str(DEFAULT_RESULTS),
                   help="Stored perception, used to index what was observed, not just claimed")
    p.add_argument("--fresh", action="store_true",
                   help="Rebuild from scratch instead of upserting into the existing index")
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

    bundle, stale = build_collections(
        rows, index_dir=Path(args.index_dir), evidence_csv=Path(args.evidence_csv),
        fraud_patterns_yaml=Path(args.fraud_patterns), results_json=Path(args.results),
        fresh=args.fresh,
    )
    for name in (HISTORICAL_CLAIMS, POLICY_RULES, FRAUD_PATTERNS):
        meta = bundle.meta.get(name)
        marker = "  (rebuilt — source changed)" if name in stale else ""
        print(f"{name:18}: {meta.count if meta else 0:3d} documents  "
              f"fingerprint {meta.fingerprint if meta else '-'}{marker}")
    print(f"Manifest    : {Path(args.index_dir) / 'manifest.json'}  (index_version {INDEX_VERSION})")
    print("No API calls were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
