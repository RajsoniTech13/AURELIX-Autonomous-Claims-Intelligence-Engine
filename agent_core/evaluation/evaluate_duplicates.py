"""
Measure duplicate-image detection: precision on genuine pairs, recall on real re-uploads.

Run: `python -m agent_core.evaluation.evaluate_duplicates`

**Precision matters more than recall here**, and the asymmetry is not a preference. A false
negative means a fraudulent claim is scored on its merits — the outcome we would have had
anyway without this feature. A false positive is an accusation of fraud against an honest
claimant, made by arithmetic. So the thresholds are chosen from the precision side and
recall is reported as whatever follows.

Two corpora, and the difference between them is the finding:

* `tests/fixtures/images` — real photographs. The only valid corpus for this measurement.
* `agent_core/data/synthetic/images` — procedurally rendered. **Cannot** measure this
  feature: every car case renders the same car template with a small damage mark, so
  different claims genuinely produce near-identical images. It is reported anyway, because
  "we measured it and the number is meaningless" is a result, and a reader who assumes the
  synthetic accuracy figure covers this feature needs to see why it does not.

Zero API cost. No model is involved anywhere in this file.
"""
from __future__ import annotations

import glob
import io
import itertools
import os
from pathlib import Path
from typing import Dict, Iterator, List, Sequence, Tuple

from PIL import Image, ImageEnhance

from agent_core.agents.image_quality import measure_image
from agent_core.retrieval.hashing import fingerprint, hamming
from agent_core.retrieval.image_index import load_retrieval_config

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_IMAGES = REPO_ROOT / "tests" / "fixtures" / "images"
SYNTHETIC_IMAGES = REPO_ROOT / "agent_core" / "data" / "synthetic" / "images"


def transformations(img: Image.Image) -> Iterator[Tuple[str, Image.Image]]:
    """What actually happens to a photograph between two submissions of it."""
    w, h = img.size
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=55)
    buf.seek(0)
    yield "re-encoded (JPEG q55)", Image.open(buf)
    yield "resized 50%", img.resize((max(1, w // 2), max(1, h // 2)), Image.LANCZOS)
    yield "resized 200%", img.resize((w * 2, h * 2), Image.LANCZOS)
    yield "cropped 4%", img.crop((int(w * .04), int(h * .04), int(w * .96), int(h * .96)))
    yield "cropped 10%", img.crop((int(w * .10), int(h * .10), int(w * .90), int(h * .90)))
    yield "brightened 20%", ImageEnhance.Brightness(img).enhance(1.2)
    yield "darkened 20%", ImageEnhance.Brightness(img).enhance(0.8)
    yield "greyscaled", img.convert("L").convert("RGB")


def _thresholds() -> Tuple[int, int]:
    cfg = load_retrieval_config()["duplicate_detection"]["near_duplicate"]
    return int(cfg["max_phash_distance"]), int(cfg["max_dhash_distance"])


def _matches(a, b, max_p: int, max_d: int) -> bool:
    return hamming(a.phash, b.phash) <= max_p and hamming(a.dhash, b.dhash) <= max_d


def _load(directory: Path, quality_gated: bool) -> Dict[str, Image.Image]:
    """Load images, optionally applying the Phase 4.1 gate that the index also applies."""
    out: Dict[str, Image.Image] = {}
    for path in sorted(glob.glob(str(directory / "*.jpg"))):
        img = Image.open(path).convert("RGB")
        if quality_gated and measure_image(img).band == "unusable":
            continue
        out[os.path.basename(path)] = img
    return out


def evaluate(directory: Path, label: str, quality_gated: bool = True) -> dict:
    max_p, max_d = _thresholds()
    images = _load(directory, quality_gated)
    fps = {name: fingerprint(img) for name, img in images.items()}

    print(f"\n{'=' * 72}\n{label}  —  {len(images)} images"
          f"{' (quality-gated)' if quality_gated else ''}\n{'=' * 72}")
    if len(images) < 2:
        print("  too few images to measure")
        return {}

    # ── Precision: distinct photographs must not match each other ──
    pairs = list(itertools.combinations(sorted(fps), 2))
    false_positives = [(a, b) for a, b in pairs if _matches(fps[a], fps[b], max_p, max_d)]
    closest = min(
        (max(hamming(fps[a].phash, fps[b].phash), hamming(fps[a].dhash, fps[b].dhash)), a, b)
        for a, b in pairs
    )
    print(f"\nPRECISION  ({len(pairs)} genuine pairs, threshold pHash<={max_p} AND dHash<={max_d})")
    print(f"  false positives : {len(false_positives)}  "
          f"({100 * len(false_positives) / len(pairs):.1f}% of pairs)")
    print(f"  closest genuine pair: {closest[1]} / {closest[2]} at {closest[0]} bits")
    for a, b in false_positives[:5]:
        print(f"    FP: {a} ~ {b} "
              f"(pHash {hamming(fps[a].phash, fps[b].phash)}, dHash {hamming(fps[a].dhash, fps[b].dhash)})")
    if len(false_positives) > 5:
        print(f"    ... and {len(false_positives) - 5} more")

    # ── Recall: a re-uploaded photograph must match its original ──
    print(f"\nRECALL  (each transformation applied to all {len(images)} images)")
    per_transform: Dict[str, List[bool]] = {}
    worst: Dict[str, Tuple[int, int]] = {}
    for name, img in images.items():
        base = fps[name]
        for tname, timg in transformations(img):
            fp = fingerprint(timg)
            per_transform.setdefault(tname, []).append(_matches(base, fp, max_p, max_d))
            pd, dd = hamming(base.phash, fp.phash), hamming(base.dhash, fp.dhash)
            prev = worst.get(tname, (0, 0))
            worst[tname] = (max(prev[0], pd), max(prev[1], dd))

    detected = total = 0
    for tname, hits in per_transform.items():
        detected += sum(hits)
        total += len(hits)
        wp, wd = worst[tname]
        flag = "" if all(hits) else "   <-- missed"
        print(f"  {tname:24} {sum(hits):2d}/{len(hits):<2d}   "
              f"worst pHash {wp:2d}, dHash {wd:2d}{flag}")
    print(f"\n  overall recall: {detected}/{total} = {100 * detected / total:.1f}%")

    return {
        "images": len(images), "pairs": len(pairs),
        "false_positives": len(false_positives),
        "recall": detected / total if total else 0.0,
    }


def main() -> int:
    max_p, max_d = _thresholds()
    print("AURELIX — duplicate-image detection")
    print(f"Thresholds from config/retrieval.yaml: pHash <= {max_p} AND dHash <= {max_d}")

    real = evaluate(REAL_IMAGES, "REAL PHOTOGRAPHS  (the corpus these thresholds are set from)")
    synth = evaluate(SYNTHETIC_IMAGES, "SYNTHETIC RENDERS  (cannot measure this feature — see below)")

    print(f"\n{'=' * 72}\nREADING THESE NUMBERS\n{'=' * 72}")
    if real:
        print(f"  Real photographs : {real['false_positives']} false positives in "
              f"{real['pairs']} genuine pairs, {100 * real['recall']:.0f}% recall.")
    if synth:
        print(f"  Synthetic renders: {synth['false_positives']} 'false positives' in "
              f"{synth['pairs']} pairs.")
        print("""
  The synthetic figure is not a defect in the detector. Every car case in that set
  renders the same car template at the same angle, differing only by a small damage
  mark, so two different claims genuinely produce near-identical photographs — some
  at a distance of 0 bits on both hashes. The detector is reporting the truth about
  the corpus. It means the synthetic set cannot validate this feature, and the 93.2%
  accuracy figure from the synthetic benchmark says nothing about duplicate detection.

  Perceptual matching is therefore disabled for synthetic benchmark runs; exact
  content-hash matching, which has no threshold and no false positives by
  construction, stays on everywhere.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
