"""
AURELIX — unified Gemini client.

What this module guarantees, and why each guarantee exists:

1. **It never fabricates a result.** There is no mock fallback. If the model cannot be
   reached, `LLMUnavailableError` propagates and the pipeline records an honest
   `not_enough_information` + reason. The previous version caught every exception and
   returned a hardcoded `claim_status="supported", confidence=85`, which fired six times
   in a three-claim audit trace and produced confident approvals for claims the model
   never saw.

2. **Retries actually happen.** The retry decorator used to be dead code: a broad
   `try/except` *inside* the wrapped function swallowed the exception before the decorator
   could see it. The error handling now lives in exactly one place — the retry loop.

3. **It respects the real quota.** Limits come from `config/limits.yaml`, which records what
   the API actually reports (5 RPM on free tier for gemini-2.5-flash), not the 15 RPM the
   code used to assume.

4. **Backoff is server-directed.** Gemini returns a structured `RetryInfo.retryDelay`. We
   read it from the parsed error body rather than regex-matching the English prose of the
   exception string.

Threading model: synchronous, guarded by a mutex. Phase 2 replaces this with an async
client and a Redis-backed token bucket shared across worker processes.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Type, TypeVar

from PIL import Image
from pydantic import BaseModel

from agent_core.services.config import (
    active_tier,
    circuit_breaker_config,
    model_config,
    model_limits,
    retry_config,
)
from agent_core.services.quota_ledger import QuotaLedger

_quota_ledger = QuotaLedger()

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("aurelix.gemini")

DEFAULT_MODEL = "gemini-3.6-flash"


# ─── Failure surface ────────────────────────────────────────────────────────

class LLMUnavailableError(RuntimeError):
    """
    The model could not produce a usable answer.

    This is the honest terminal state. It is deliberately NOT caught inside this module:
    callers must decide what a missing answer means for their verdict, and the only
    correct answer for a claim verdict is `not_enough_information`.
    """

    def __init__(self, message: str, *, attempts: int = 0, last_status: Optional[int] = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_status = last_status


class CircuitOpenError(LLMUnavailableError):
    """Raised while the breaker is open, so we fail fast instead of stampeding the API."""


class DailyQuotaExhausted(LLMUnavailableError):
    """
    The per-day request budget for this model is spent.

    Split out from ordinary rate limiting because the correct response is the opposite:
    an RPM 429 should be waited out, an RPD 429 cannot be. On a 20-request daily budget,
    retrying a daily exhaustion four times destroys 20% of the next day's capacity to
    learn something the first response already told us.
    """

    def __init__(self, message: str, model: str = ""):
        super().__init__(message)
        self.model = model


# ─── Error classification ───────────────────────────────────────────────────

def _status_code(exc: BaseException) -> Optional[int]:
    """Pull the HTTP status off a google-genai APIError, if that's what this is."""
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def _quota_scope(exc: BaseException) -> Optional[str]:
    """
    Classify a 429 as 'per_minute' or 'per_day' from the structured quota violation.

    Gemini reports which budget was hit:
        quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier
        quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier

    Returns None when this is not a quota error or the scope cannot be determined.
    """
    if _status_code(exc) != 429:
        return None

    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        error_obj = details.get("error", details)
        for item in error_obj.get("details", []) or []:
            if not isinstance(item, dict) or not item.get("@type", "").endswith("QuotaFailure"):
                continue
            for violation in item.get("violations", []) or []:
                qid = str(violation.get("quotaId", ""))
                if "PerDay" in qid:
                    return "per_day"
                if "PerMinute" in qid:
                    return "per_minute"

    # Fall back to the message text if the structured form is missing.
    text = str(exc)
    if "PerDay" in text:
        return "per_day"
    if "PerMinute" in text:
        return "per_minute"
    return None


def _is_retryable(exc: BaseException) -> bool:
    """
    Retry transport failures and server-side congestion. Never retry 400/401/403 —
    a malformed request or a bad key will fail identically every time, and retrying
    only delays the moment someone notices the bug.
    """
    # A daily exhaustion is never retryable. Waiting will not help before midnight UTC,
    # and every attempt spends budget we do not have.
    if _quota_scope(exc) == "per_day":
        return False

    code = _status_code(exc)
    if code is not None:
        return code in set(retry_config()["retryable_status_codes"])
    # No status code => transport-level failure (DNS, connection reset, read timeout).
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def _server_requested_delay(exc: BaseException) -> Optional[float]:
    """
    Read `RetryInfo.retryDelay` out of the structured error body.

    Gemini returns e.g.
        details: [{'@type': '...google.rpc.RetryInfo', 'retryDelay': '47s'}]
    Preferring this over our own backoff is what keeps us from being throttled again
    immediately on the next attempt.
    """
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return None
    error_obj = details.get("error", details)
    for item in error_obj.get("details", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("@type", "").endswith("RetryInfo"):
            raw = str(item.get("retryDelay", "")).strip()
            if raw.endswith("s"):
                try:
                    return float(raw[:-1])
                except ValueError:
                    return None
    return None


# ─── Circuit breaker ────────────────────────────────────────────────────────

class _CircuitBreaker:
    """Trip after N consecutive failures; refuse calls for a cooldown; reset on success."""

    def __init__(self) -> None:
        cfg = circuit_breaker_config()
        self._threshold: int = cfg["failure_threshold"]
        self._cooldown: float = cfg["cooldown_seconds"]
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed < self._cooldown:
                raise CircuitOpenError(
                    f"circuit breaker is open after {self._failures} consecutive failures; "
                    f"retrying in {self._cooldown - elapsed:.0f}s"
                )
            # Cooldown elapsed — allow one probe through.
            self._opened_at = None
            self._failures = 0

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.error(
                    "[Gemini] Circuit opened after %d consecutive failures; "
                    "failing fast for %.0fs", self._failures, self._cooldown
                )


_breaker = _CircuitBreaker()


# ─── Rate governor ──────────────────────────────────────────────────────────

class RateGovernor:
    """
    Per-model sliding-window governor enforcing RPM and TPM together.

    The old implementation spaced calls by a fixed interval derived from an assumed RPM.
    That is not a quota: it cannot represent a burst budget, it cannot see token spend,
    and when it was configured 3x too high it simply metered traffic straight into a wall
    of 429s. This tracks actual request and token timestamps against the configured
    window, so `acquire` blocks only when the real budget is exhausted.

    Process-local. Phase 2 backs this with a Redis Lua token bucket so N workers share
    one budget instead of each believing it owns the whole quota.
    """

    _WINDOW = 60.0
    _DAY = 86400.0

    def __init__(self) -> None:
        self._requests: Dict[str, deque[float]] = {}
        self._tokens: Dict[str, deque[tuple[float, int]]] = {}
        self._daily: Dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, model: str, now: float) -> None:
        reqs = self._requests.setdefault(model, deque())
        toks = self._tokens.setdefault(model, deque())
        daily = self._daily.setdefault(model, deque())
        cutoff = now - self._WINDOW
        while reqs and reqs[0] <= cutoff:
            reqs.popleft()
        while toks and toks[0][0] <= cutoff:
            toks.popleft()
        day_cutoff = now - self._DAY
        while daily and daily[0] <= day_cutoff:
            daily.popleft()

    def remaining_daily(self, model: str) -> int:
        """How many requests are left in today's budget, as this process sees it."""
        with self._lock:
            self._prune(model, time.monotonic())
            return max(0, model_limits(model)["rpd"] - len(self._daily[model]))

    def acquire(self, model: str, est_tokens: int = 0) -> float:
        """
        Block until this request fits inside both the RPM and TPM budgets.
        Returns seconds spent waiting, for instrumentation.
        """
        limits = model_limits(model)
        rpm, tpm, rpd = limits["rpm"], limits["tpm"], limits["rpd"]
        waited = 0.0

        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(model, now)
                reqs = self._requests[model]
                toks = self._tokens[model]
                daily = self._daily[model]

                # The daily budget is not something to wait out — on free tier the window
                # is 24 hours. Refuse immediately so the caller gets an honest error state
                # instead of a process that appears to hang until tomorrow.
                if len(daily) >= rpd:
                    raise LLMUnavailableError(
                        f"daily request budget for {model} is exhausted "
                        f"({rpd} requests/day on tier '{active_tier()}'). "
                        f"Raise the quota or switch tiers in config/limits.yaml."
                    )

                spent = sum(t for _, t in toks)
                rpm_ok = len(reqs) < rpm
                tpm_ok = (spent + est_tokens) <= tpm

                if rpm_ok and tpm_ok:
                    reqs.append(now)
                    daily.append(now)
                    if est_tokens:
                        toks.append((now, est_tokens))
                    return waited

                # Sleep exactly until the oldest relevant entry ages out of the window.
                candidates = []
                if not rpm_ok and reqs:
                    candidates.append(reqs[0] + self._WINDOW - now)
                if not tpm_ok and toks:
                    candidates.append(toks[0][0] + self._WINDOW - now)
                sleep_for = max(0.05, min(candidates) if candidates else 0.05)

            reason = "RPM" if not rpm_ok else "TPM"
            logger.info("[RateGovernor] %s budget for %s exhausted; waiting %.1fs", reason, model, sleep_for)
            time.sleep(sleep_for)
            waited += sleep_for


governor = RateGovernor()


def estimate_tokens(prompt: str, image_count: int = 0) -> int:
    """
    Pre-flight token estimate for TPM accounting.

    ~4 chars/token for English text; Gemini bills roughly 258 tokens per image tile at
    default resolution. Deliberately rough and deliberately an over-estimate — the cost
    of over-estimating is a slightly slower queue, the cost of under-estimating is a 429.
    """
    return len(prompt) // 4 + image_count * 258


# ─── Cache ──────────────────────────────────────────────────────────────────

_inmemory_cache: Dict[str, str] = {}
_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    """One connection for the process, not one per cache operation."""
    global _redis_client
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                try:
                    import redis
                    _redis_client = redis.from_url(url)
                except Exception as e:  # noqa: BLE001 - cache is optional by design
                    logger.warning("[Cache] Redis unavailable, using in-memory only: %s", e)
                    return None
    return _redis_client


def compute_cache_key(
    agent_name: str,
    user_id: str = "",
    claim_text: str = "",
    image_bytes_hash: str = "",
    prompt_version: str = "v2",
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Deterministic idempotency key.

    Includes prompt_version and model so that changing a prompt or switching models
    invalidates the cache instead of silently serving answers from the old configuration.
    """
    raw = f"{agent_name}:{user_id}:{claim_text.strip()}:{image_bytes_hash}:{prompt_version}:{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_image_bytes(images: List[Image.Image]) -> str:
    """
    Content hash over the full pixel data of every image.

    The previous version hashed only `tobytes()[:4096]` — the first few scanlines — so two
    photographs sharing a patch of sky collided and returned each other's cached analysis.
    """
    if not images:
        return "no_images"
    h = hashlib.sha256()
    for img in images:
        h.update(str(img.size).encode())
        h.update(img.convert("RGB").tobytes())
    return h.hexdigest()


def _cache_get(key: str) -> Optional[str]:
    r = _get_redis()
    if r is not None:
        try:
            val = r.get(key)
            if val:
                return val.decode("utf-8") if isinstance(val, bytes) else val
        except Exception as e:  # noqa: BLE001
            logger.warning("[Cache] Redis get failed: %s", e)
    return _inmemory_cache.get(key)


def _cache_set(key: str, value: str, ttl_seconds: int = 3600) -> None:
    r = _get_redis()
    if r is not None:
        try:
            r.setex(key, ttl_seconds, value)
        except Exception as e:  # noqa: BLE001
            logger.warning("[Cache] Redis set failed: %s", e)
    _inmemory_cache[key] = value


# ─── Client ─────────────────────────────────────────────────────────────────

_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise LLMUnavailableError(
                    "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
                )
            from google import genai
            _client = genai.Client(api_key=api_key)
    return _client


def _execute_with_retry(call, *, description: str):
    """
    The single place where LLM errors are handled.

    Exponential backoff with full jitter, capped, server-directed delay preferred.
    Non-retryable errors are re-raised immediately rather than burning attempts.
    """
    cfg = retry_config()
    max_attempts: int = cfg["max_attempts"]
    base: float = cfg["base_delay_seconds"]
    cap: float = cfg["max_delay_seconds"]

    _breaker.check()
    last_exc: Optional[BaseException] = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = call()
            _breaker.record_success()
            return result
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            last_exc = exc
            code = _status_code(exc)

            if _quota_scope(exc) == "per_day":
                # Not a breaker failure: the API is healthy, we are simply out of budget.
                model_name = getattr(call, "_aurelix_model", "") or ""
                _quota_ledger.mark_exhausted(model_name)
                raise DailyQuotaExhausted(
                    f"{description}: daily request quota exhausted for "
                    f"{model_name or 'this model'}. Stopping rather than retrying; "
                    f"remaining work is checkpointed for the next quota reset.",
                    model=model_name,
                ) from exc

            if not _is_retryable(exc):
                _breaker.record_failure()
                raise LLMUnavailableError(
                    f"{description} failed with a non-retryable error "
                    f"({code or type(exc).__name__}): {exc}",
                    attempts=attempt,
                    last_status=code,
                ) from exc

            if attempt == max_attempts:
                break

            # Server-directed delay wins; otherwise exponential backoff with full jitter.
            server_delay = _server_requested_delay(exc)
            if server_delay is not None:
                delay = min(server_delay + 0.5, cap)
                source = "server RetryInfo"
            else:
                delay = random.uniform(0, min(cap, base * (2 ** (attempt - 1))))
                source = "jittered backoff"

            logger.warning(
                "[Gemini] %s: retryable %s on attempt %d/%d; sleeping %.1fs (%s)",
                description, code or type(exc).__name__, attempt, max_attempts, delay, source,
            )
            time.sleep(delay)

    _breaker.record_failure()
    raise LLMUnavailableError(
        f"{description} exhausted {max_attempts} attempts; last error: {last_exc}",
        attempts=max_attempts,
        last_status=_status_code(last_exc) if last_exc else None,
    ) from last_exc


def _generate(
    *,
    contents: Any,
    response_model: Type[T],
    model: str,
    temperature: float,
    cache_key: Optional[str],
    est_tokens: int,
    description: str,
) -> T:
    if cache_key:
        cached = _cache_get(cache_key)
        if cached:
            logger.info("[Cache] hit for %s", description)
            return response_model.model_validate_json(cached)

    from google.genai import types

    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=response_model,
    )

    def _call() -> T:
        governor.acquire(model, est_tokens)
        client = _get_client()
        # Recorded before the call, not after: a request that fails on the server side has
        # still consumed budget, and under-counting is the expensive direction of error.
        _quota_ledger.record_request(model)
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:
            # Refund anything the server did not actually process. 5xx means it declined
            # the work; 400/403/404 means it rejected the request outright. Neither should
            # count against a 20-per-day budget. Measured impact: a model that 404s on
            # every call silently consumed 13 slots of recorded budget in the first run.
            if _status_code(exc) in (400, 403, 404, 500, 502, 503, 504):
                _quota_ledger.refund_request(model)
            raise
        text = (response.text or "").strip()
        if not text:
            # A blocked or empty completion is a failure, not an empty verdict.
            raise LLMUnavailableError(f"{description} returned an empty response body")
        return response_model.model_validate_json(text)

    _call._aurelix_model = model  # type: ignore[attr-defined]  # for quota attribution
    result = _execute_with_retry(_call, description=description)

    if cache_key:
        _cache_set(cache_key, result.model_dump_json())
    return result


# ─── Public API ─────────────────────────────────────────────────────────────

def call_gemini_text(
    prompt: str,
    response_model: Type[T],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    cache_key: Optional[str] = None,
) -> T:
    """
    Text-only structured call.

    Raises `LLMUnavailableError` on failure. It does not return a placeholder, and callers
    must not convert this into a verdict — see `DecisionOutput.from_failure`.
    """
    return _generate(
        contents=prompt,
        response_model=response_model,
        model=model,
        temperature=temperature,
        cache_key=cache_key,
        est_tokens=estimate_tokens(prompt),
        description=f"{response_model.__name__} (text)",
    )


def call_gemini_vision(
    images: List[Image.Image],
    prompt: str,
    response_model: Type[T],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    cache_key: Optional[str] = None,
) -> T:
    """Multimodal structured call. Same failure contract as `call_gemini_text`."""
    if not images:
        raise ValueError("call_gemini_vision requires at least one image")
    contents: List[Any] = [*images, prompt]
    return _generate(
        contents=contents,
        response_model=response_model,
        model=model,
        temperature=temperature,
        cache_key=cache_key,
        est_tokens=estimate_tokens(prompt, image_count=len(images)),
        description=f"{response_model.__name__} (vision, {len(images)} image(s))",
    )


# ─── Batched multimodal, with a free-tier model ladder ──────────────────────

def remaining_requests(model: str) -> int:
    """Requests left today for a model, per the persisted ledger."""
    return _quota_ledger.remaining(model, model_limits(model)["rpd"])


def quota_summary() -> str:
    chain = model_config()["chain"]
    return _quota_ledger.summary({m: model_limits(m)["rpd"] for m in chain})


def call_gemini_multimodal(
    contents: List[Any],
    response_model: Type[T],
    model: Optional[str] = None,
    temperature: float = 0.1,
    cache_key: Optional[str] = None,
    description: str = "multimodal",
) -> T:
    """
    Arbitrary interleaved text+image content, structured response.

    Walks the configured model ladder. Free-tier quota is **per model**, so when the primary
    is exhausted the next model is a fresh 20-request budget rather than a wall — three
    free models is 60 requests/day without paying anything. A model is skipped when the
    ledger already knows it is spent, so we do not burn a request rediscovering that.

    Raises `DailyQuotaExhausted` only when every rung is spent.
    """
    chain: List[str] = [model] if model else list(model_config()["chain"])
    image_count = sum(1 for part in contents if isinstance(part, Image.Image))
    text_len = sum(len(p) for p in contents if isinstance(p, str))
    est = estimate_tokens("x" * text_len, image_count=image_count)

    # Cache lookup is model-independent: a cached perception is equally valid whichever
    # rung produced it.
    if cache_key:
        cached = _cache_get(cache_key)
        if cached:
            logger.info("[Cache] hit for %s", description)
            return response_model.model_validate_json(cached)

    last_error: Optional[BaseException] = None
    tried: List[str] = []

    for candidate in chain:
        if remaining_requests(candidate) <= 0:
            logger.warning("[Gemini] skipping %s: daily budget already spent", candidate)
            tried.append(f"{candidate}(spent)")
            continue
        try:
            result = _generate(
                contents=contents,
                response_model=response_model,
                model=candidate,
                temperature=temperature,
                cache_key=None,          # written once below, after success
                est_tokens=est,
                description=f"{description} on {candidate}",
            )
            if cache_key:
                _cache_set(cache_key, result.model_dump_json())
            return result
        except DailyQuotaExhausted as e:
            logger.warning("[Gemini] %s exhausted; advancing to next model", candidate)
            tried.append(f"{candidate}(exhausted)")
            last_error = e
            continue
        except LLMUnavailableError as e:
            # A model that is persistently 503 or timing out is as unusable as one that is
            # out of quota, and the ladder is the right response to both. Only give up once
            # every rung has been tried.
            logger.warning("[Gemini] %s unavailable (%s); advancing to next model", candidate, e)
            tried.append(f"{candidate}(unavailable)")
            last_error = e
            continue

    if isinstance(last_error, DailyQuotaExhausted) or not last_error:
        raise DailyQuotaExhausted(
            f"{description}: every configured model is out of daily free quota "
            f"(tried {', '.join(tried) or 'none'}). Work is checkpointed; resume after reset.",
        ) from last_error

    raise LLMUnavailableError(
        f"{description}: no configured model could serve this request "
        f"(tried {', '.join(tried)}). Last error: {last_error}"
    ) from last_error
