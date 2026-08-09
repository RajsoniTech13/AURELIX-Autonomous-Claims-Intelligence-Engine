"""
Persistent daily request ledger.

On a 20-requests-per-day budget, forgetting what today already spent is expensive. The
in-memory governor resets on every process start, so a crash-and-rerun would happily burn
through a budget it has already used. This ledger survives restarts.

Keyed by (model, Pacific date), because that is when Google's free-tier daily quota actually
resets.

This started as a UTC key, which was wrong in the dangerous direction: UTC midnight arrives
seven to eight hours *before* Pacific midnight, so the ledger would zero itself while the
real quota was still spent — exactly the over-optimism it exists to prevent. Observed live:
a run recorded 20/20 against gemini-3.6-flash, and the next run an hour later believed the
budget was untouched.

Deliberately a plain JSON file. It is read once and written after each request; a database
here would be infrastructure for a counter.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict

_DEFAULT_PATH = Path(os.getenv("AURELIX_STATE_DIR", ".aurelix")) / "quota_state.json"


_RESET_TZ = ZoneInfo("America/Los_Angeles")


def _today() -> str:
    """The quota day, in the timezone the provider resets on."""
    return datetime.now(_RESET_TZ).strftime("%Y-%m-%d")


class QuotaLedger:
    """Tracks requests spent per model per day, and which models are known exhausted."""

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, int]] = {}
        self._exhausted: Dict[str, str] = {}   # model -> date it was observed exhausted
        self._load()

    # ─── persistence ────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # a corrupt ledger must not stop the pipeline; we just recount from zero
        self._state = data.get("spent", {})
        self._exhausted = data.get("exhausted", {})

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"spent": self._state, "exhausted": self._exhausted}, indent=1),
                encoding="utf-8",
            )
            tmp.replace(self._path)   # atomic, so a crash mid-write cannot corrupt it
        except OSError:
            pass

    # ─── accounting ─────────────────────────────────────────────────────────

    def spent_today(self, model: str) -> int:
        with self._lock:
            return self._state.get(_today(), {}).get(model, 0)

    def record_request(self, model: str) -> None:
        with self._lock:
            day = self._state.setdefault(_today(), {})
            day[model] = day.get(model, 0) + 1
            # Drop history older than today; this is a budget, not an audit log.
            for old in [d for d in self._state if d != _today()]:
                del self._state[old]
            self._save()

    def refund_request(self, model: str) -> None:
        """
        Give back a request the server explicitly refused to process.

        A 503 "high demand" means the model declined the work before doing any of it, so
        counting it against a 20-request daily budget would make us give up capacity we
        still have. Only ever called for errors that clearly indicate no work was done.
        """
        with self._lock:
            day = self._state.setdefault(_today(), {})
            if day.get(model):
                day[model] -= 1
                self._save()

    def mark_exhausted(self, model: str) -> None:
        if not model:
            return
        with self._lock:
            self._exhausted[model] = _today()
            self._save()

    def is_exhausted(self, model: str) -> bool:
        with self._lock:
            return self._exhausted.get(model) == _today()

    def remaining(self, model: str, limit: int) -> int:
        if self.is_exhausted(model):
            return 0
        return max(0, limit - self.spent_today(model))

    def reset(self) -> None:
        """Test hook."""
        with self._lock:
            self._state, self._exhausted = {}, {}
            self._save()

    def summary(self, limits: Dict[str, int]) -> str:
        parts = [f"{m}: {self.spent_today(m)}/{lim}"
                 + (" EXHAUSTED" if self.is_exhausted(m) else "")
                 for m, lim in limits.items()]
        return "  ".join(parts)
