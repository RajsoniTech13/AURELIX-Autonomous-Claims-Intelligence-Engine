"""
AURELIX — CLI entry point.

`python -m agent_core.main` is the documented command and still works, but it is now a thin
front for `agent_core.run_pipeline`. The old implementation drove the ten-node graph at four
LLM calls per claim, which cannot run a 44-claim batch inside a 20-request free daily budget
at all — see docs/FREE_TIER_DESIGN.md.

The batched runner does the same job in ~15 requests: deterministic preflight, one
multimodal request per three claims, then deterministic judgement, with per-claim
checkpointing so an exhausted budget resumes rather than restarts.

`run_pipeline` has the full flag set (`--dry-run`, `--fresh`, `--no-resume`, `--checkpoint`).
This wrapper exposes the ones the original CLI had.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_core.run_pipeline import run  # noqa: E402
from agent_core.services.checkpoint import CheckpointStore  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent

DEFAULT_CLAIMS = BASE_DIR / "data" / "synthetic" / "claims_synthetic.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description="AURELIX claims verification batch runner")
    parser.add_argument(
        "--claims", default=str(DEFAULT_CLAIMS),
        help="Claims CSV to process (default: the synthetic evaluation set)",
    )
    parser.add_argument(
        "--image-root", default=os.getenv("AURELIX_IMAGE_ROOT", str(REPO_ROOT)),
        help="Root directory that relative image_paths resolve against (default: repo root)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan the batches and report the request cost without calling the API",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Clear the checkpoint first. Costs a full re-run of the daily budget.",
    )
    args = parser.parse_args()

    print("=== AURELIX agent-core CLI (batched multimodal pipeline) ===")

    claims_csv = Path(args.claims)
    if not claims_csv.exists():
        print(f"Error: claims file not found: {claims_csv}", file=sys.stderr)
        return 1

    if not os.getenv("GEMINI_API_KEY") and not args.dry_run:
        print(
            "Error: GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 1

    store = CheckpointStore(".aurelix/checkpoint.db")
    if args.fresh:
        store.clear()
        print("Checkpoint cleared.")

    run(
        claims_csv=claims_csv,
        image_root=Path(args.image_root),
        output_csv=BASE_DIR / "output" / "output.csv",
        results_json=BASE_DIR / "output" / "results_detail.json",
        store=store,
        resume=not args.fresh,
        dry_run=args.dry_run,
    )
    print("=== Done ===")
    print("Score against ground truth with: "
          "python -m agent_core.evaluation.evaluate_synthetic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
