"""
Batched claim pipeline runner.

Two passes, and the split is what makes the free tier work:

  1. **Perception** — deterministic preflight, then one multimodal Gemini request per batch
     of ~3 claims. 44 claims become ~15 requests instead of 176.
  2. **Judgement** — pure Python. Alignment, fraud score, confidence, verdict, rule ids.
     No model involvement, so this pass costs nothing and is byte-for-byte reproducible.

Everything is checkpointed per claim. If the daily budget runs out at request 12 of 15, the
finished claims are already durable and the next run picks up the remainder rather than
paying for them again.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_core.agents.alignment import compute_alignment  # noqa: E402
from agent_core.agents.image_quality import UNMEASURED, PreflightQuality  # noqa: E402
from agent_core.agents.image_validator import preflight  # noqa: E402
from agent_core.agents.perception import (  # noqa: E402
    BatchIsolationError,
    PreparedClaim,
    run_batch_perception,
)
from agent_core.retrieval.image_index import DuplicateMatch, ImageIndex, indexable  # noqa: E402
from agent_core.schemas.contract import image_id  # noqa: E402
from agent_core.schemas.perception import ClaimPerception  # noqa: E402
from agent_core.schemas.contract import OUTPUT_COLUMNS  # noqa: E402
from agent_core.service import judge, to_output_row  # noqa: E402
from agent_core.services.batch_scheduler import affordable_batches, describe_plan, plan_batches  # noqa: E402
from agent_core.services.checkpoint import CheckpointStore  # noqa: E402
from agent_core.services.config import batching_config, model_config  # noqa: E402
from agent_core.services.gemini_client import (  # noqa: E402
    DailyQuotaExhausted,
    LLMUnavailableError,
    quota_summary,
    remaining_requests,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ─── Loading ────────────────────────────────────────────────────────────────

def measure_claim_quality(row: Dict[str, str], image_root: Path) -> PreflightQuality:
    """
    Deterministic blur/exposure measurement for one claim's images.

    Kept as a standalone function because it is needed twice: once in preflight for claims
    about to be sent, and again when re-deriving verdicts for claims perceived on an earlier
    run. Measuring from the files both times costs nothing and keeps the two paths honest —
    a stored measurement could silently drift from the image it describes.
    """
    _, _, quality = preflight(
        row.get("image_paths", ""), base_dir=str(image_root),
        max_images=batching_config()["max_images_per_claim"],
    )
    return quality


def prepare_claims(
    rows: List[Dict[str, str]],
    image_root: Path,
    skip_ids: set[str],
    image_index: Optional[ImageIndex] = None,
) -> tuple[List[PreparedClaim], List[Dict[str, Any]], Dict[str, PreflightQuality],
           Dict[str, List[DuplicateMatch]]]:
    """
    Preflight every claim. Returns (claims worth sending, rows resolved without the model,
    measured image quality per claim id).

    Claims with no usable image never reach Gemini: they cannot produce a grounded finding,
    so spending a slot of a 20-request budget on them would be waste.
    """
    max_images = batching_config()["max_images_per_claim"]
    sendable: List[PreparedClaim] = []
    resolved: List[Dict[str, Any]] = []
    quality_by_id: Dict[str, PreflightQuality] = {}
    duplicates_by_id: Dict[str, List[DuplicateMatch]] = {}

    for row in rows:
        claim_id = row.get("claim_id") or row.get("user_id", "")
        if claim_id in skip_ids:
            continue

        validation, images, quality = preflight(
            row.get("image_paths", ""), base_dir=str(image_root), max_images=max_images,
        )
        quality_by_id[claim_id] = quality

        # Duplicate check before insert, and before any request, so a claim is compared
        # only against what preceded it.
        if image_index is not None and images and indexable(quality.overall):
            ids = [image_id(i) for i in range(len(images))]
            found = image_index.find_duplicates(
                images, claim_id=claim_id, user_id=row.get("user_id", ""), image_ids=ids,
            )
            if found:
                duplicates_by_id[claim_id] = found
            image_index.add_claim_images(claim_id, row.get("user_id", ""), images, ids)

        if not validation.valid:
            resolved.append({
                "claim_id": claim_id, "row": row, "perception": None,
                "no_usable_image": True, "validation": validation,
                "preflight_quality": quality,
                "duplicate_matches": duplicates_by_id.get(claim_id, []),
            })
            continue

        sendable.append(PreparedClaim(
            claim_id=claim_id,
            claim_object=row.get("claim_object", ""),
            claim_text=row.get("user_claim", ""),
            images=images,
            raw=row,
        ))

    return sendable, resolved, quality_by_id, duplicates_by_id


# ─── Runner ─────────────────────────────────────────────────────────────────

def run(
    claims_csv: Path,
    image_root: Path,
    output_csv: Path,
    results_json: Path,
    store: CheckpointStore,
    resume: bool = True,
    dry_run: bool = False,
    image_index: Optional[ImageIndex] = None,
) -> Dict[str, Any]:
    with claims_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    done = store.completed_ids() if resume else set()
    if done:
        print(f"Resuming: {len(done)} claim(s) already complete, skipping them.")

    sendable, resolved, quality_by_id, duplicates_by_id = prepare_claims(
        rows, image_root, done, image_index=image_index,
    )
    print(f"{len(rows)} claims: {len(sendable)} need perception, "
          f"{len(resolved)} resolved at preflight, {len(done)} already done.")

    batches = plan_batches(sendable)
    print(f"Plan: {describe_plan(batches)}")

    # Budget is the sum across the whole ladder, not just the primary. Free quota is
    # per-model, so an exhausted primary is a rung rather than a wall — counting only
    # the primary would defer batches we can actually afford.
    budget = sum(remaining_requests(m) for m in model_config()["chain"])
    print(f"Quota: {quota_summary()}")
    print(f"  Total free requests available across the ladder: {budget}")

    payable, deferred = affordable_batches(batches, budget)
    if deferred:
        print(f"  Budget allows {len(payable)} of {len(batches)} batches today; "
              f"{len(deferred)} deferred to the next reset.")

    if dry_run:
        return {"planned_batches": len(batches), "affordable": len(payable), "dry_run": True}

    entries: List[Dict[str, Any]] = list(resolved)
    stopped_early = False

    for batch in payable:
        print(f"\n[{batch.batch_id}] {len(batch)} claims / {batch.image_count} images: "
              f"{', '.join(batch.claim_ids)}")
        t0 = time.perf_counter()
        try:
            perceptions = run_batch_perception(batch.claims)
            dt = time.perf_counter() - t0
            print(f"  ok in {dt:.1f}s")
            for claim in batch.claims:
                entries.append({
                    "claim_id": claim.claim_id, "row": claim.raw,
                    "perception": perceptions.get(claim.claim_id),
                    "preflight_quality": quality_by_id.get(claim.claim_id),
                    "duplicate_matches": duplicates_by_id.get(claim.claim_id, []),
                    "batch_id": batch.batch_id, "model": model_config()["primary"],
                })
        except DailyQuotaExhausted as e:
            print(f"  DAILY QUOTA EXHAUSTED: {e}")
            print("  Stopping cleanly. Remaining claims are checkpointed for the next reset.")
            stopped_early = True
            break
        except BatchIsolationError as e:
            # Never accept a result we cannot vouch for; a contaminated verdict is
            # indistinguishable from a good one downstream.
            print(f"  ISOLATION FAILURE: {e}")
            for claim in batch.claims:
                entries.append({
                    "claim_id": claim.claim_id, "row": claim.raw, "perception": None,
                    "perception_failed": True, "batch_id": batch.batch_id,
                    "error": f"isolation: {e}",
                })
        except LLMUnavailableError as e:
            print(f"  PERCEPTION FAILED: {e}")
            for claim in batch.claims:
                entries.append({
                    "claim_id": claim.claim_id, "row": claim.raw, "perception": None,
                    "perception_failed": True, "batch_id": batch.batch_id, "error": str(e),
                })

        # Checkpoint after every batch, so a later failure cannot lose earlier work.
        judged = [judge(e) for e in entries if e.get("batch_id") == batch.batch_id]
        store.commit_batch([{
            "claim_id": j["claim_id"], "batch_id": j["batch_id"], "model": j["model"],
            "status": "failed" if j.get("error") else "done",
            "raw_perception": j["perception"].model_dump() if j["perception"] else None,
            "normalized_result": to_output_row(j),
            "fraud_score": j["verdict"].fraud_score,
            "confidence": j["verdict"].confidence,
            "decision": j["verdict"].claim_status,
            "rule_ids": j["verdict"].rule_ids,
            "error": j.get("error"),
        } for j in judged])

    for batch in deferred:
        for claim in batch.claims:
            entries.append({
                "claim_id": claim.claim_id, "row": claim.raw, "perception": None,
                "perception_failed": True, "batch_id": batch.batch_id,
                "error": "deferred: daily request budget reserved",
            })

    results = [judge(e) for e in entries]
    results.sort(key=lambda r: r["claim_id"])

    output_rows = {r["claim_id"]: to_output_row(r) for r in results}

    def _detail(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "claim_id": r["claim_id"],
            "batch_id": r["batch_id"],
            "verdict": r["verdict"].to_dict(),
            "alignment": r["alignment"].to_dict() if r["alignment"] else None,
            "perception": r["perception"].model_dump() if r["perception"] else None,
            # Kept beside the model's own quality claim rather than replacing it, so a
            # reviewer can see both what the model said and what the pixels said.
            "preflight_quality": r["preflight_quality"].to_dict() if r.get("preflight_quality") else None,
            "error": r["error"],
        }

    detail_by_id = {r["claim_id"]: _detail(r) for r in results}

    # Re-derive claims completed on earlier runs. The judgement pass is a pure function of
    # the stored perception, so replaying it costs nothing and needs no API call — which is
    # the practical payoff of keeping the decision logic out of the model.
    #
    # **The replay feeds output.csv as well as results_detail.json.** It used to feed only
    # the detail file, while the CSV fell back to the `normalized_result` frozen into the
    # checkpoint at the time the claim was first analysed. So after a rule or ontology fix,
    # a resumed run produced an evaluation report showing the corrected verdicts and a
    # graded CSV still carrying the old ones — the two deliverables disagreeing, with the
    # stale one being the contract.
    row_by_id = {(r.get("claim_id") or r.get("user_id", "")): r for r in rows}
    for rec in store.all_results():
        cid = rec["claim_id"]
        if cid in detail_by_id:
            continue
        if not rec.get("raw_perception"):
            # No stored perception to re-derive from (e.g. a claim resolved at preflight).
            # The checkpointed row is all there is, and it does not depend on rules.
            if rec.get("normalized_result"):
                output_rows[cid] = json.loads(rec["normalized_result"])
            continue
        perception = ClaimPerception.model_validate(json.loads(rec["raw_perception"]))
        row = row_by_id.get(cid, {})
        replayed = judge({
            "claim_id": cid, "row": row, "perception": perception,
            "preflight_quality": quality_by_id.get(cid) or measure_claim_quality(row, image_root),
            "batch_id": rec.get("batch_id"), "model": rec.get("model"),
        })
        detail_by_id[cid] = _detail(replayed)
        output_rows[cid] = to_output_row(replayed)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(OUTPUT_COLUMNS))
        w.writeheader()
        for cid in sorted(output_rows):
            w.writerow(output_rows[cid])

    detail = [detail_by_id[k] for k in sorted(detail_by_id)]
    results_json.parent.mkdir(parents=True, exist_ok=True)
    results_json.write_text(json.dumps(detail, indent=1, default=str), encoding="utf-8")

    print(f"\nWrote {output_csv}  ({len(output_rows)} rows)")
    print(f"Wrote {results_json}")
    print(f"Checkpoint: {store.status_counts()}")
    print(f"Quota after run: {quota_summary()}")

    return {
        "claims": len(rows), "batches_planned": len(batches), "batches_run": len(payable),
        "stopped_early": stopped_early, "rows_written": len(output_rows),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="AURELIX batched claim pipeline")
    p.add_argument("--claims", default="agent_core/data/synthetic/claims_synthetic.csv")
    p.add_argument("--image-root", default=str(REPO_ROOT))
    p.add_argument("--output", default="agent_core/output/output.csv")
    p.add_argument("--results", default="agent_core/output/results_detail.json")
    p.add_argument("--checkpoint", default=".aurelix/checkpoint.db")
    p.add_argument("--no-resume", action="store_true", help="Ignore prior checkpoint state")
    p.add_argument("--fresh", action="store_true", help="Clear the checkpoint before running")
    p.add_argument("--dry-run", action="store_true", help="Plan batches without calling the API")
    p.add_argument(
        "--duplicate-detection", action="store_true",
        help="Check each claim's images against the index (see the note below; OFF for the "
             "synthetic benchmark on purpose)",
    )
    args = p.parse_args()

    if not os.getenv("GEMINI_API_KEY") and not args.dry_run:
        print("Error: GEMINI_API_KEY is not set.", file=sys.stderr)
        return 1

    store = CheckpointStore(args.checkpoint)
    if args.fresh:
        store.clear()
        print("Checkpoint cleared.")

    # Duplicate detection defaults OFF for this runner, which is a statement about the
    # dataset rather than about the feature. Every car case in the synthetic set renders
    # the same template at the same angle, differing only by a small damage mark, so two
    # *different* claims produce genuinely near-identical images -- 110 of 1035 pairs match,
    # some at 0 bits on both hashes. Enabling it here would measure the corpus, not the
    # system, and would silently corrupt the accuracy figure. Real photographs behave
    # entirely differently: 0 false positives. See docs/PHASE_4.4_REPORT.md and
    # `python -m agent_core.evaluation.evaluate_duplicates`.
    index = ImageIndex() if args.duplicate_detection else None
    if index is not None:
        print(f"Duplicate detection ON against {index.count()} indexed fingerprints.")

    run(
        claims_csv=Path(args.claims), image_root=Path(args.image_root),
        output_csv=Path(args.output), results_json=Path(args.results),
        store=store, resume=not args.no_resume, dry_run=args.dry_run,
        image_index=index,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
