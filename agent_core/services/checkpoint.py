"""
Resumable per-claim checkpoint store.

The system is deliberately built around a small daily quota, which makes resumability a
correctness requirement rather than a nicety: a run that stops after 12 of 15 requests must
resume at claim 37 tomorrow, not reprocess claim 1 and burn the budget again.

SQLite because it gives atomic commits and survives a kill -9. A batch commits all-or-
nothing: a partially parsed response must leave no half-written claims behind, or the next
run will trust results that were never validated.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_DEFAULT_PATH = Path(os.getenv("AURELIX_STATE_DIR", ".aurelix")) / "checkpoint.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS claim_results (
    claim_id            TEXT PRIMARY KEY,
    batch_id            TEXT,
    model               TEXT,
    status              TEXT NOT NULL,
    raw_perception      TEXT,
    normalized_result   TEXT,
    fraud_score         INTEGER,
    confidence          INTEGER,
    decision            TEXT,
    rule_ids            TEXT,
    error               TEXT,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status ON claim_results(status);
"""

# pending -> in the plan, not yet attempted
# done -> perception succeeded and rules ran; never reprocessed
# failed -> a real error specific to this claim
# quota_deferred -> nothing wrong with it, we simply ran out of budget today
VALID_STATUS = ("pending", "done", "failed", "quota_deferred")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointStore:
    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── reads ──────────────────────────────────────────────────────────────

    def completed_ids(self) -> set[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT claim_id FROM claim_results WHERE status = 'done'"
            ).fetchall()
        return {r["claim_id"] for r in rows}

    def get(self, claim_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM claim_results WHERE claim_id = ?", (claim_id,)
            ).fetchone()
        return dict(row) if row else None

    def all_results(self) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM claim_results ORDER BY claim_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def status_counts(self) -> Dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM claim_results GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ─── writes ─────────────────────────────────────────────────────────────

    def commit_batch(self, records: Iterable[Dict[str, Any]]) -> int:
        """
        Write a whole batch atomically.

        All-or-nothing on purpose: if any record in a batch is malformed we would rather
        write none and retry the batch than leave a mix that the next run treats as done.
        """
        rows = []
        for r in records:
            status = r.get("status", "pending")
            if status not in VALID_STATUS:
                raise ValueError(f"invalid checkpoint status {status!r}")
            rows.append((
                r["claim_id"],
                r.get("batch_id"),
                r.get("model"),
                status,
                json.dumps(r["raw_perception"], default=str) if r.get("raw_perception") is not None else None,
                json.dumps(r["normalized_result"], default=str) if r.get("normalized_result") is not None else None,
                r.get("fraud_score"),
                r.get("confidence"),
                r.get("decision"),
                ";".join(r.get("rule_ids") or []) or None,
                r.get("error"),
                _now(),
            ))

        with closing(self._connect()) as conn:
            with conn:  # transaction: commits on success, rolls back on any exception
                conn.executemany(
                    """INSERT INTO claim_results
                       (claim_id, batch_id, model, status, raw_perception, normalized_result,
                        fraud_score, confidence, decision, rule_ids, error, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(claim_id) DO UPDATE SET
                         batch_id=excluded.batch_id, model=excluded.model,
                         status=excluded.status, raw_perception=excluded.raw_perception,
                         normalized_result=excluded.normalized_result,
                         fraud_score=excluded.fraud_score, confidence=excluded.confidence,
                         decision=excluded.decision, rule_ids=excluded.rule_ids,
                         error=excluded.error, updated_at=excluded.updated_at""",
                    rows,
                )
        return len(rows)

    def clear(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute("DELETE FROM claim_results")
