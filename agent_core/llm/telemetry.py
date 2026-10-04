"""
Per-call telemetry for every model request AURELIX makes.

What it records. One `CallRecord` per network attempt — and one per cache hit, so a cache
can be seen working — carrying provider, model, task, prompt version, token counts,
latency, list-price cost and outcome. **Never the prompt text, the answer, or anything a
claimant wrote.** Telemetry ends up in a database that more people can read than can read
claims, so it holds counts and labels only.

How it is wired. The code that makes the network call is the code that emits the record:
`services/gemini_client.py` for Gemini, the adapters for everyone else. That rule keeps one
record per real request with no double counting. Everything else listens:

* `subscribe(fn)` — the web backend subscribes a database writer at startup. The CLI
  subscribes nothing, so a benchmark run writes no telemetry.
* `collect()` — a context manager that captures the records emitted inside it. The gateway
  uses it to read back the tokens and latency of the call an adapter just made, without
  every adapter having to return them through a second channel.
* `call_context(...)` — labels the records emitted inside it with a task, a request id and
  a prompt version. The caller knows what the call was *for*; the client making it does not.

A listener that raises is logged and ignored. Losing a telemetry row is acceptable; failing
a claim because a metrics write failed is not.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, Iterator, List, Optional

from agent_core.llm import pricing

logger = logging.getLogger("aurelix.telemetry")

# Outcome labels. A closed set, so a metrics query can group on it.
OK = "ok"
RATE_LIMITED = "rate_limited"
QUOTA_EXHAUSTED = "quota_exhausted"
AUTH_ERROR = "auth_error"
UNAVAILABLE = "unavailable"
INVALID_RESPONSE = "invalid_response"
OUTCOMES = frozenset({OK, RATE_LIMITED, QUOTA_EXHAUSTED, AUTH_ERROR, UNAVAILABLE, INVALID_RESPONSE})


@dataclass
class CallRecord:
    task: str
    provider: str
    model: str
    outcome: str = OK
    prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: Optional[float] = None
    cache_hit: bool = False
    request_id: Optional[str] = None
    claim_id: Optional[int] = None
    error_type: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Context: what the call was for ─────────────────────────────────────────

_context: contextvars.ContextVar[Dict[str, object]] = contextvars.ContextVar(
    "aurelix_llm_context", default={},
)


@contextlib.contextmanager
def call_context(**labels: object) -> Iterator[None]:
    """
    Label records emitted inside this block. Nests: inner labels override outer ones.

    A ContextVar rather than a global so two claims analysed on two threads cannot label
    each other's calls. Note that a *new* thread starts with an empty context, so the block
    must be opened on the thread that makes the call.
    """
    token = _context.set({**_context.get(), **{k: v for k, v in labels.items() if v is not None}})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> Dict[str, object]:
    return dict(_context.get())


def prompt_fingerprint(text: str, name: str) -> str:
    """
    A content-addressed prompt version, e.g. `perception@3f2a9c1d`.

    Used where a prompt has no hand-maintained version number. It cannot drift from the
    prompt it describes: edit one character and the version changes.
    """
    return f"{name}@{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]}"


# ─── Emission ───────────────────────────────────────────────────────────────

_listeners: List[Callable[[CallRecord], None]] = []
_listeners_lock = threading.Lock()
# A tuple of every active collector, innermost last. Collectors nest — the gateway collects
# around an adapter call while its caller may be collecting around the gateway — and each
# must see every record emitted inside it, not only the innermost one.
_collectors: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "aurelix_llm_collectors", default=(),
)


def subscribe(listener: Callable[[CallRecord], None]) -> Callable[[], None]:
    """Register a listener. Returns a function that unregisters it."""
    with _listeners_lock:
        _listeners.append(listener)

    def unsubscribe() -> None:
        with _listeners_lock:
            if listener in _listeners:
                _listeners.remove(listener)

    return unsubscribe


@contextlib.contextmanager
def collect() -> Iterator[List[CallRecord]]:
    """Capture the records emitted inside this block, in order."""
    records: List[CallRecord] = []
    token = _collectors.set(_collectors.get() + (records,))
    try:
        yield records
    finally:
        _collectors.reset(token)


def emit(record: CallRecord) -> None:
    """Hand a record to the active collector and every listener. Never raises."""
    for captured in _collectors.get():
        captured.append(record)
    with _listeners_lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(record)
        except Exception as exc:  # noqa: BLE001 - telemetry must never fail a request
            logger.warning("[Telemetry] listener %r failed: %s", listener, exc)


def record_call(
    *,
    provider: str,
    model: str,
    outcome: str = OK,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cache_hit: bool = False,
    error_type: Optional[str] = None,
) -> CallRecord:
    """
    Build a record from the call's facts plus the current context, price it, and emit it.

    A cache hit is priced at zero: no tokens went to a provider. A failed call is priced on
    whatever tokens the provider reported, which is usually none.
    """
    ctx = current_context()
    cost = 0.0 if cache_hit else pricing.cost_usd(provider, model, input_tokens, output_tokens)
    claim_id = ctx.get("claim_id")
    record = CallRecord(
        task=str(ctx.get("task") or "unlabelled"),
        provider=provider,
        model=model,
        outcome=outcome if outcome in OUTCOMES else UNAVAILABLE,
        prompt_version=str(ctx.get("prompt_version") or ""),
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        latency_ms=int(latency_ms or 0),
        cost_usd=cost,
        cache_hit=cache_hit,
        request_id=str(ctx["request_id"]) if ctx.get("request_id") else None,
        claim_id=int(claim_id) if isinstance(claim_id, int) else None,
        error_type=error_type,
    )
    emit(record)
    return record
