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
from agent_core.agents.image_validator import load_valid_images, run_image_validator  # noqa: E402
from agent_core.agents.perception import (  # noqa: E402
    BatchIsolationError,
    PreparedClaim,
    run_batch_perception,
)
from agent_core.rules_engine import decide  # noqa: E402
from agent_core.schemas.perception import ClaimPerception  # noqa: E402
from agent_core.schemas.contract import OUTPUT_COLUMNS, coerce_to_vocabulary, join_multi, to_bool_str  # noqa: E402
from agent_core.schemas.contract import ISSUE_TYPE_VALUES, OBJECT_PART_VALUES, SEVERITY_VALUES  # noqa: E402
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

def prepare_claims(
    rows: List[Dict[str, str]],
    image_root: Path,
    skip_ids: set[str],
) -> tuple[List[PreparedClaim], List[Dict[str, Any]]]:
    """
    Preflight every claim. Returns (claims worth sending, rows resolved without the model).

    Claims with no usable image never reach Gemini: they cannot produce a grounded finding,
    so spending a slot of a 20-request budget on them would be waste.
    """
    max_images = batching_config()["max_images_per_claim"]
    sendable: List[PreparedClaim] = []
    resolved: List[Dict[str, Any]] = []

    for row in rows:
        claim_id = row.get("claim_id") or row.get("user_id", "")
        if claim_id in skip_ids:
            continue

        validation = run_image_validator(
            images=None, image_paths_str=row.get("image_paths", ""), base_dir=str(image_root),
        )
        if not validation.valid:
            resolved.append({
                "claim_id": claim_id, "row": row, "perception": None,
                "no_usable_image": True, "validation": validation,
            })
            continue

        images = load_valid_images(
            row.get("image_paths", ""), base_dir=str(image_root), max_images=max_images,
        )
        sendable.append(PreparedClaim(
            claim_id=claim_id,
            claim_object=row.get("claim_object", ""),
            claim_text=row.get("user_claim", ""),
            images=images,
            raw=row,
        ))

    return sendable, resolved


# ─── Judgement (pure Python) ────────────────────────────────────────────────

def judge(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Alignment + rules for one claim. No LLM, fully reproducible."""
    perception = entry.get("perception")
    row = entry["row"]

    alignment = compute_alignment(perception, row.get("claim_object", "")) if perception else None

    verdict = decide(
        alignment, perception,
        no_usable_image=entry.get("no_usable_image", False),
        perception_failed=entry.get("perception_failed", False),
        extra_risk_flags=list(getattr(entry.get("validation"), "risk_flags", []) or []),
    )

    return {
        "claim_id": entry["claim_id"],
        "row": row,
        "perception": perception,
        "alignment": alignment,
        "verdict": verdict,
        "batch_id": entry.get("batch_id"),
        "model": entry.get("model"),
        "error": entry.get("error"),
    }


def to_output_row(result: Dict[str, Any]) -> Dict[str, str]:
    """Render one judged claim into the frozen 14-column contract."""
    row, perception, verdict = result["row"], result["perception"], result["verdict"]
    alignment = result["alignment"]

    issue_type, object_part, severity = "unknown", "unknown", "unknown"
    supporting: List[str] = []
    if perception:
        damages = perception.damage_analysis.damaged_parts
        chosen = None
        if alignment and alignment.matched_part:
            chosen = next((d for d in damages if d.part == alignment.matched_part), None)
        chosen = chosen or (damages[0] if damages else None)
        if chosen:
            issue_type = coerce_to_vocabulary(chosen.issue_type, ISSUE_TYPE_VALUES, "unknown")
            object_part = coerce_to_vocabulary(chosen.part, OBJECT_PART_VALUES, "unknown")
            severity = coerce_to_vocabulary(chosen.severity, SEVERITY_VALUES, "unknown")
        elif perception.claimed_part_visible:
            issue_type, severity = "none", "none"
        supporting = [s for s in perception.supporting_image_ids if s.startswith("img_")]

    evidence_met = bool(perception and perception.image_quality.overall in ("good", "fair"))
    evidence_reason = (
        f"Image quality assessed {perception.image_quality.overall} "
        f"(score {perception.image_quality.score})."
        if perception else "No usable image evidence was submitted with this claim."
    )

    return {
        "user_id": row.get("user_id", ""),
        "image_paths": row.get("image_paths", ""),
        "user_claim": row.get("user_claim", ""),
        "claim_object": row.get("claim_object", ""),
        "evidence_standard_met": to_bool_str(evidence_met),
        "evidence_standard_met_reason": evidence_reason,
        "risk_flags": join_multi(verdict.risk_flags, empty="none"),
        "issue_type": issue_type,
        "object_part": object_part,
        "claim_status": verdict.claim_status,
        "claim_status_justification": verdict.justification,
        "supporting_image_ids": join_multi(supporting, empty="none"),
        "valid_image": to_bool_str(bool(perception)),
        "severity": severity,
    }


# ─── Runner ─────────────────────────────────────────────────────────────────

def run(
    claims_csv: Path,
    image_root: Path,
    output_csv: Path,
    results_json: Path,
    store: CheckpointStore,
    resume: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    with claims_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    done = store.completed_ids() if resume else set()
    if done:
        print(f"Resuming: {len(done)} claim(s) already complete, skipping them.")

    sendable, resolved = prepare_claims(rows, image_root, done)
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

    # Merge in claims completed on earlier runs so the output file is always complete.
    output_rows = {r["claim_id"]: to_output_row(r) for r in results}
    for rec in store.all_results():
        if rec["claim_id"] not in output_rows and rec.get("normalized_result"):
            output_rows[rec["claim_id"]] = json.loads(rec["normalized_result"])

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(OUTPUT_COLUMNS))
        w.writeheader()
        for cid in sorted(output_rows):
            w.writerow(output_rows[cid])

    def _detail(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "claim_id": r["claim_id"],
            "batch_id": r["batch_id"],
            "verdict": r["verdict"].to_dict(),
            "alignment": r["alignment"].to_dict() if r["alignment"] else None,
            "perception": r["perception"].model_dump() if r["perception"] else None,
            "error": r["error"],
        }

    detail_by_id = {r["claim_id"]: _detail(r) for r in results}

    # Re-derive detail for claims completed on earlier runs. The judgement pass is a pure
    # function of the stored perception, so replaying it costs nothing and needs no API
    # call — which is the practical payoff of keeping the decision logic out of the model.
    row_by_id = {(r.get("claim_id") or r.get("user_id", "")): r for r in rows}
    for rec in store.all_results():
        cid = rec["claim_id"]
        if cid in detail_by_id or not rec.get("raw_perception"):
            continue
        perception = ClaimPerception.model_validate(json.loads(rec["raw_perception"]))
        replayed = judge({
            "claim_id": cid, "row": row_by_id.get(cid, {}), "perception": perception,
            "batch_id": rec.get("batch_id"), "model": rec.get("model"),
        })
        detail_by_id[cid] = _detail(replayed)

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
    args = p.parse_args()

    if not os.getenv("GEMINI_API_KEY") and not args.dry_run:
        print("Error: GEMINI_API_KEY is not set.", file=sys.stderr)
        return 1

    store = CheckpointStore(args.checkpoint)
    if args.fresh:
        store.clear()
        print("Checkpoint cleared.")

    run(
        claims_csv=Path(args.claims), image_root=Path(args.image_root),
        output_csv=Path(args.output), results_json=Path(args.results),
        store=store, resume=not args.no_resume, dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
