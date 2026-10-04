"""
Capacity control for a public demonstration deployment.

AURELIX runs entirely on free-tier infrastructure, and the binding constraint is not
CPU or memory but **Gemini's free daily request budget**: 20 requests per model per
day across a three-model ladder, so 60 analyses a day for every visitor combined.

That number is small enough to be spent by accident. A single curious visitor running
six claims takes 10% of the day. A link shared somewhere busy exhausts it in under an
hour — and then the budget is gone until midnight Pacific, for everyone, including
whoever the link was actually shared with.

Two mechanisms, and they do different jobs:

* **A per-visitor daily cap** stops one person consuming the shared budget. It is a
  fairness device, not a security control — it is keyed on client IP, which is
  trivially changed. That is fine: the goal is to stop ordinary over-enthusiasm, not
  a determined adversary, and there is nothing here worth attacking.

* **A reserve floor** keeps the last few requests unspendable by casual traffic, so
  the system is never *completely* out of live capacity during a working day.

When capacity is gone the answer is not an error. The product stays fully browsable —
every previously analysed investigation is still there — and the UI says plainly when
live analysis resumes. A demo that degrades legibly reads as engineering; a demo that
throws reads as breakage.

State is in-process and deliberately so. The service runs one worker (see render.yaml),
the counters are worth nothing if lost, and a restart resetting them is the correct
failure direction for a fairness cap: it forgives rather than accuses.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

# Gemini's free-tier daily budget resets at midnight America/Los_Angeles. The visitor
# cap uses the same boundary so that "resets at" means one thing in the UI rather than
# two subtly different things.
#
# A named zone, not a fixed UTC-8 offset. The fixed offset ignored daylight saving: under
# PDT it put the day boundary an hour late, so for an hour each day this module and the
# quota ledger (which always used the named zone) disagreed about what day it was, and the
# reset time shown to visitors was wrong. Measured on 2026-10-04: it reported a reset at
# 08:00Z that had already passed; the real one was 07:00Z the next day.
_PACIFIC = ZoneInfo("America/Los_Angeles")


def _today() -> str:
    return datetime.now(_PACIFIC).strftime("%Y-%m-%d")


def next_reset() -> datetime:
    """Midnight Pacific, expressed in UTC so a browser can render it locally."""
    now = datetime.now(_PACIFIC)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return tomorrow.astimezone(timezone.utc)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def per_visitor_limit() -> int:
    """Live analyses one visitor may run per day. 0 disables the cap entirely."""
    return _int_env("DEMO_PER_IP_DAILY", 4)


def reserve_floor() -> int:
    """Model requests held back from casual traffic."""
    return _int_env("DEMO_RESERVE_FLOOR", 6)


def enabled() -> bool:
    """
    Off by default outside a deployment.

    Local development and the test suite must not inherit a public site's rationing —
    a cap that silently applies in CI turns an unrelated test failure into a mystery.
    """
    return (os.getenv("DEMO_MODE", "") or "").strip().lower() in {"1", "true", "yes", "on"}


# ─── Visitor ledger ─────────────────────────────────────────────────────────

_lock = threading.Lock()
_spent: Dict[str, Dict[str, int]] = {}   # {date: {visitor: count}}


def _bucket() -> Dict[str, int]:
    """Today's counters, discarding any earlier day rather than accumulating them."""
    day = _today()
    if day not in _spent:
        _spent.clear()
        _spent[day] = {}
    return _spent[day]


def visitor_key(client_host: Optional[str], forwarded_for: Optional[str] = None) -> str:
    """
    Identify a visitor for rationing.

    Render terminates TLS at a proxy, so `request.client.host` is the proxy and every
    visitor collapses into one bucket — which would cap the entire site at four
    analyses a day. `X-Forwarded-For` carries the original client as the first entry.

    That header is client-supplied and therefore spoofable. It is trusted here anyway,
    because the alternative is a cap that does not work at all, and the consequence of
    a spoof is one extra analysis rather than any access to anything.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return client_host or "unknown"


# ─── Model capacity ─────────────────────────────────────────────────────────

def model_capacity() -> Tuple[int, int]:
    """
    `(remaining, total)` requests across the whole model ladder.

    Reads the same persisted ledger the client itself consults, so this cannot drift
    from what an analysis would actually find when it tried.
    """
    try:
        from agent_core.services.config import model_config, model_limits
        from agent_core.services.gemini_client import remaining_requests

        chain = model_config()["chain"]
        remaining = sum(max(0, remaining_requests(m)) for m in chain)
        total = sum(model_limits(m)["rpd"] for m in chain)
        return remaining, total
    except Exception:  # noqa: BLE001
        # An unreadable ledger must not block submission. The analysis itself raises
        # DailyQuotaExhausted if the budget really is gone, and that path is honest.
        return -1, -1


# ─── The decision ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    detail: str = ""


def check(visitor: str) -> Decision:
    """Whether this visitor may spend a model request right now. Does not consume."""
    if not enabled():
        return Decision(allowed=True)

    remaining, _ = model_capacity()
    if remaining >= 0 and remaining <= reserve_floor():
        return Decision(
            allowed=False,
            reason="daily_capacity_reached",
            detail=(
                "The shared free-tier analysis budget for today is spent. Every "
                "investigation already on file remains fully browsable, and live "
                "analysis resumes at midnight Pacific."
            ),
        )

    limit = per_visitor_limit()
    if limit > 0:
        with _lock:
            used = _bucket().get(visitor, 0)
        if used >= limit:
            return Decision(
                allowed=False,
                reason="visitor_limit_reached",
                detail=(
                    f"You have run {used} live analyses today, which is this "
                    f"demonstration's per-visitor limit. It exists so the shared "
                    f"free-tier budget is still there for the next visitor. Browsing "
                    f"and every completed investigation are unaffected."
                ),
            )

    return Decision(allowed=True)


def consume(visitor: str) -> None:
    """Record that this visitor started a live analysis."""
    if not enabled():
        return
    with _lock:
        bucket = _bucket()
        bucket[visitor] = bucket.get(visitor, 0) + 1


def status(visitor: str) -> dict:
    """Everything the UI needs to explain the current state without guessing."""
    remaining, total = model_capacity()
    limit = per_visitor_limit()
    with _lock:
        used = _bucket().get(visitor, 0) if enabled() else 0

    decision = check(visitor)
    return {
        "demo_mode": enabled(),
        "live_analysis_available": decision.allowed,
        "reason": decision.reason or None,
        "detail": decision.detail or None,
        "visitor_used_today": used,
        "visitor_limit": limit if enabled() else None,
        "capacity_remaining": remaining if remaining >= 0 else None,
        "capacity_total": total if total >= 0 else None,
        "resets_at": next_reset().isoformat(),
    }
