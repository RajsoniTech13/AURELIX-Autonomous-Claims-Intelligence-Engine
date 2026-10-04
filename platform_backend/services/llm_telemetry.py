"""
Model-call telemetry, persisted and summarised for the operator.

`agent_core.llm.telemetry` emits one record per model attempt and knows nothing about
databases. This module is the web backend's listener: it writes each record to the
`llm_calls` table, links calls to the claim they served once that claim exists, and turns
the table into the numbers `GET /api/v1/metrics/llm` reports.

Two properties matter more than the numbers themselves:

* **Writing telemetry can never fail a claim.** The writer opens its own session, commits
  on its own, and swallows its own errors. The worst case is a missing metrics row.
* **Every figure is computed from rows, not estimated.** p50/p95 are nearest-rank
  percentiles over recorded latencies; cost per claim is the sum of recorded list-price
  cost divided by the number of claims those calls are linked to.
"""
from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from agent_core.llm import pricing, telemetry
from platform_backend.db import session as session_module
from platform_backend.db.models import LLMCall

logger = logging.getLogger("aurelix.llm_telemetry")

_unsubscribe = None


def write_record(record: telemetry.CallRecord) -> None:
    """Persist one record on a session of its own. Never raises."""
    db = session_module.SessionLocal()
    try:
        db.add(LLMCall(
            task=record.task[:50],
            provider=record.provider[:30],
            model=record.model[:80],
            prompt_version=(record.prompt_version or None),
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            latency_ms=record.latency_ms,
            cost_usd=record.cost_usd,
            cache_hit=record.cache_hit,
            outcome=record.outcome,
            error_type=record.error_type,
            request_id=record.request_id,
            claim_id=record.claim_id,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a lost metrics row is acceptable, a failed claim is not
        db.rollback()
        logger.warning("[Telemetry] could not persist call record: %s", exc)
    finally:
        db.close()


def install() -> None:
    """Subscribe the database writer. Idempotent: a second call does nothing."""
    global _unsubscribe
    if _unsubscribe is None:
        _unsubscribe = telemetry.subscribe(write_record)


def uninstall() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None


def link_calls_to_claim(db: Session, request_id: Optional[str], claim_id: int) -> int:
    """
    Attach this submission's model calls to the claim row they produced.

    The perception call happens *before* the claim row exists, so it is recorded with the
    submission's `request_id` and given its `claim_id` here, after the claim is saved.
    """
    if db is None or not request_id or claim_id is None:
        return 0
    try:
        updated = (
            db.query(LLMCall)
            .filter(LLMCall.request_id == request_id, LLMCall.claim_id.is_(None))
            .update({LLMCall.claim_id: claim_id}, synchronize_session=False)
        )
        db.commit()
        return updated
    except Exception as exc:  # noqa: BLE001 - the claim is already saved; never undo that
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("[Telemetry] could not link calls to claim %s: %s", claim_id, exc)
        return 0


# ─── Summary ────────────────────────────────────────────────────────────────

def percentile(values: List[int], p: float) -> Optional[int]:
    """Nearest-rank percentile: the smallest value with at least p% of samples at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _quota_view() -> List[Dict[str, Any]]:
    """Today's Gemini usage per model, from the same ledger the client consults."""
    from agent_core.services.config import model_config, model_limits, text_tasks_config
    from agent_core.services.gemini_client import remaining_requests

    models: List[str] = list(model_config()["chain"])
    for task in text_tasks_config().values():
        for rung in task.get("ladder", []):
            if rung.get("provider") == "gemini" and rung["model"] not in models:
                models.append(rung["model"])

    view = []
    for model in models:
        limit = int(model_limits(model)["rpd"])
        remaining = remaining_requests(model)
        view.append({
            "provider": "gemini", "model": model, "limit_per_day": limit,
            "used_today": max(0, limit - remaining), "remaining_today": remaining,
        })
    return view


def summarise(db: Session, days: int = 7) -> Dict[str, Any]:
    days = max(1, min(int(days), 90))
    since = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=days)
    rows: List[LLMCall] = db.query(LLMCall).filter(LLMCall.created_at >= since).all()

    network = [r for r in rows if not r.cache_hit]
    succeeded = [r for r in network if r.outcome == telemetry.OK]

    per_day: Dict[str, Dict[str, int]] = {}
    for r in rows:
        day = r.created_at.strftime("%Y-%m-%d")
        bucket = per_day.setdefault(day, {"calls": 0, "failures": 0, "cache_hits": 0})
        if r.cache_hit:
            bucket["cache_hits"] += 1
        else:
            bucket["calls"] += 1
            if r.outcome != telemetry.OK:
                bucket["failures"] += 1

    by_task: Dict[str, Dict[str, Any]] = {}
    for task in sorted({r.task for r in rows}):
        task_rows = [r for r in rows if r.task == task]
        ok = [r.latency_ms for r in task_rows if not r.cache_hit and r.outcome == telemetry.OK]
        costs = [r.cost_usd for r in task_rows if r.cost_usd is not None]
        by_task[task] = {
            "calls": sum(1 for r in task_rows if not r.cache_hit),
            "cache_hits": sum(1 for r in task_rows if r.cache_hit),
            "failures": sum(1 for r in task_rows if not r.cache_hit and r.outcome != telemetry.OK),
            "p50_latency_ms": percentile(ok, 50),
            "p95_latency_ms": percentile(ok, 95),
            "cost_usd": round(sum(costs), 9),
        }

    linked = [r for r in rows if r.claim_id is not None and r.cost_usd is not None]
    claims = {r.claim_id for r in linked}
    total_cost = sum(r.cost_usd for r in rows if r.cost_usd is not None)
    unpriced = sum(1 for r in network if r.cost_usd is None)

    return {
        "window_days": days,
        "totals": {
            "calls": len(network),
            "failures": len(network) - len(succeeded),
            "cache_hits": len(rows) - len(network),
            "cache_hit_rate": round((len(rows) - len(network)) / len(rows), 4) if rows else None,
        },
        "latency_ms": {
            "p50": percentile([r.latency_ms for r in succeeded], 50),
            "p95": percentile([r.latency_ms for r in succeeded], 95),
            "samples": len(succeeded),
        },
        "cost": {
            "list_price_usd": round(total_cost, 9),
            "per_claim_usd": round(sum(r.cost_usd for r in linked) / len(claims), 9) if claims else None,
            "claims_counted": len(claims),
            "unpriced_calls": unpriced,
            "billed_usd": 0.0,
            "note": "List-price equivalent. Billed cost is $0: every provider used runs on its free tier.",
            "pricing_as_of": pricing.as_of(),
        },
        "calls_per_day": [{"date": d, **v} for d, v in sorted(per_day.items())],
        "by_task": by_task,
        "quota": _quota_view(),
    }
