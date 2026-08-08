"""
AURELIX — CLI batch runner.

Reads claims from CSV, runs each through the agent graph, and writes the frozen
`output.csv` contract. Then re-runs the labelled sample set and produces an evaluation
report.

Two behaviours worth knowing about:

* **Failures are visible.** A claim that cannot be processed produces a row saying so
  (`not_enough_information` + the real reason), not a skipped row and not a guess. The
  previous version swallowed every error and wrote an empty file.
* **Progress is checkpointed.** Completed rows are flushed as they are produced, so a
  crash at claim 40 of 44 does not discard the first 39.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_core.agents.image_validator import load_valid_images  # noqa: E402
from agent_core.evaluation.evaluate import evaluate_predictions  # noqa: E402
from agent_core.orchestrator.graph import process_claim  # noqa: E402
from agent_core.output_mapper import build_output_row  # noqa: E402
from agent_core.schemas.contract import OUTPUT_COLUMNS  # noqa: E402
from agent_core.services.config import evidence_config  # noqa: E402
from agent_core.services.vector_store import index_historical_claims  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))


def _read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, mode="r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_rows(path: str, rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(OUTPUT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def run_batch(
    claims: List[Dict[str, str]],
    user_history_lookup: Dict[str, Dict[str, str]],
    evidence_rules_lookup: Dict[str, Dict[str, str]],
    image_root: str,
    output_path: str,
    label: str,
) -> List[Dict[str, str]]:
    """Process a batch of claims, flushing to `output_path` after each one."""
    rows: List[Dict[str, str]] = []
    failures = 0
    started = time.perf_counter()

    for idx, raw_claim in enumerate(claims, start=1):
        user_id = raw_claim.get("user_id", "")
        image_paths = raw_claim.get("image_paths", "")
        claim_object = raw_claim.get("claim_object", "")

        print(f"[{label} {idx}/{len(claims)}] {user_id} ({claim_object})...", flush=True)

        # Load whatever images actually exist on disk. A short list here is a real signal
        # about evidence quality and must not be padded.
        images = load_valid_images(
            image_paths,
            base_dir=image_root,
            max_images=evidence_config()["max_images_per_claim"],
        )

        try:
            state = process_claim(
                user_id=user_id,
                image_paths=image_paths,
                user_claim=raw_claim.get("user_claim", ""),
                claim_object=claim_object,
                user_history=user_history_lookup.get(user_id),
                evidence_rules=evidence_rules_lookup.get(claim_object.lower()),
                images=images,
                image_base_dir=image_root,
            )
        except Exception as e:  # noqa: BLE001
            # An unexpected crash still produces a row. Dropping the claim silently is how
            # the previous version turned 44 failures into an empty file.
            print(f"    ERROR: {type(e).__name__}: {e}", flush=True)
            failures += 1
            state = {
                "decision": {
                    "claim_status": "not_enough_information",
                    "manual_review_required": True,
                    "justification": (
                        f"Processing failed with an unexpected error "
                        f"({type(e).__name__}: {e}). No verdict was inferred."
                    ),
                },
            }

        row = build_output_row(state, raw_claim)
        rows.append(row)

        errs = state.get("pipeline_errors") or []
        status_note = f" [{len(errs)} agent error(s)]" if errs else ""
        print(f"    -> {row['claim_status']} / severity={row['severity']}{status_note}", flush=True)

        _write_rows(output_path, rows)  # checkpoint

    elapsed = time.perf_counter() - started
    print(
        f"{label}: {len(rows)} rows written, {failures} hard failures, "
        f"{elapsed:.1f}s total ({elapsed / max(len(rows), 1):.1f}s/claim)",
        flush=True,
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="AURELIX claims verification batch runner")
    parser.add_argument(
        "--image-root",
        default=os.getenv("AURELIX_IMAGE_ROOT", REPO_ROOT),
        help="Root directory that relative image_paths resolve against (default: repo root)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process only the first N claims (useful for smoke tests against a small quota)",
    )
    parser.add_argument(
        "--skip-validation-run", action="store_true",
        help="Skip the labelled sample re-run and the evaluation report",
    )
    parser.add_argument(
        "--allow-text-only", action="store_true",
        help="Permit inference from claim text when no image loads. OFF by default: "
             "findings produced this way are guesses, not observations.",
    )
    args = parser.parse_args()

    if args.allow_text_only:
        os.environ["AURELIX_ALLOW_TEXT_ONLY"] = "true"

    print("=== AURELIX agent-core CLI ===")

    claims_csv = os.path.join(BASE_DIR, "data", "claims.csv")
    user_history_csv = os.path.join(BASE_DIR, "data", "user_history.csv")
    evidence_csv = os.path.join(BASE_DIR, "data", "evidence_requirements.csv")
    sample_claims_csv = os.path.join(BASE_DIR, "data", "sample_claims.csv")
    output_csv = os.path.join(BASE_DIR, "output", "output.csv")
    validation_csv = os.path.join(BASE_DIR, "output", "validation_output.csv")
    report_md = os.path.join(BASE_DIR, "output", "evaluation_report.md")

    for fpath in (claims_csv, user_history_csv, evidence_csv, sample_claims_csv):
        if not os.path.exists(fpath):
            print(f"Error: required input not found: {fpath}", file=sys.stderr)
            return 1

    if not os.getenv("GEMINI_API_KEY"):
        print(
            "Error: GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 1

    print("Loading reference tables...")
    user_history_lookup = {r["user_id"]: r for r in _read_csv(user_history_csv)}
    evidence_rules_lookup = {r["claim_object"].lower(): r for r in _read_csv(evidence_csv)}

    index_historical_claims(sample_claims_csv)

    image_root = os.path.abspath(args.image_root)
    print(f"Resolving images against: {image_root}")
    if not os.path.isdir(os.path.join(image_root, "images")):
        allowed = evidence_config()["allow_text_only_inference"]
        print(
            f"\n  WARNING: no 'images/' directory under {image_root}.\n"
            f"  Claims referencing image files will find nothing to analyse.\n"
            f"  Text-only inference is {'ENABLED — findings will be guesses' if allowed else 'DISABLED'}, "
            f"so these claims will resolve to "
            f"{'ungrounded, low-confidence findings' if allowed else 'not_enough_information'}.\n"
            f"  Point --image-root at the directory containing images/ if you have it.\n",
            flush=True,
        )

    claims = _read_csv(claims_csv)
    if args.limit:
        claims = claims[: args.limit]

    print(f"Processing {len(claims)} claims...")
    run_batch(
        claims, user_history_lookup, evidence_rules_lookup,
        image_root, output_csv, label="batch",
    )
    print(f"Wrote {output_csv}")

    if args.skip_validation_run:
        print("Skipping validation run (--skip-validation-run).")
        return 0

    sample_claims = _read_csv(sample_claims_csv)
    if args.limit:
        sample_claims = sample_claims[: args.limit]

    print(f"\nRe-running {len(sample_claims)} labelled sample claims for evaluation...")
    run_batch(
        sample_claims, user_history_lookup, evidence_rules_lookup,
        image_root, validation_csv, label="eval",
    )

    evaluate_predictions(
        sample_path=sample_claims_csv,
        output_path=validation_csv,
        report_path=report_md,
    )
    print("=== Done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
