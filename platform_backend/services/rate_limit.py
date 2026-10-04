"""
Per-caller rate limits: a sliding window of timestamps per key.

Two different jobs from `demo_guard`. `demo_guard` rations the *shared Gemini budget* per
visitor per day. These limits stop *one account* from hammering an endpoint — submitting
claims in a loop, scripting the copilot until Groq's free tier refuses everyone, or guessing
passwords — regardless of what any budget says.

In-process, like the rest of this single-worker deployment. Multiple workers would each
enforce the limit separately; the Phase B Redis token bucket is the fix, behind this same
`check` call.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException

from agent_core.services.config import load_config


def rate_limits() -> Dict[str, int]:
    return dict(load_config().get("rate_limits") or {})


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float, *, record: bool = True) -> Optional[float]:
        """None when allowed (and recorded); otherwise seconds until the next slot frees up."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return max(1.0, hits[0] + window_seconds - now)
            if record:
                hits.append(now)
            return None

    def record(self, key: str) -> None:
        with self._lock:
            self._hits.setdefault(key, deque()).append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


window = SlidingWindow()


def enforce(key: str, limit_name: str, window_seconds: float, what: str) -> None:
    """Raise 429 with Retry-After when `key` has used up `limit_name` in the window."""
    limit = int(rate_limits().get(limit_name, 0))
    if limit <= 0:
        return
    wait = window.check(key, limit, window_seconds)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Too many {what}. Try again in {int(wait)} seconds.",
            headers={"Retry-After": str(int(wait))},
        )
