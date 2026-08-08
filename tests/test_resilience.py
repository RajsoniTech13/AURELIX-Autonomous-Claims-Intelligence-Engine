"""
Retry, backoff, rate governing, and the circuit breaker.

The retry loop used to be unreachable: a broad `try/except` inside the wrapped function
swallowed exceptions before the decorator could see them, so a 429 resolved in ~200ms with
zero retries while the server was asking for a 47-second wait. These tests assert the
loop actually runs, respects the server's RetryInfo, and refuses to retry client errors.
"""
from __future__ import annotations

import pytest

import agent_core.services.gemini_client as gc


class _APIError(Exception):
    def __init__(self, code: int, details: dict | None = None):
        super().__init__(f"{code} error")
        self.code = code
        self.details = details or {}


def _retry_info(seconds: str) -> dict:
    return {
        "error": {
            "code": 429,
            "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": seconds},
            ],
        }
    }


@pytest.fixture(autouse=True)
def _fresh_breaker(monkeypatch):
    """Each test gets its own breaker so trips don't leak across tests."""
    monkeypatch.setattr(gc, "_breaker", gc._CircuitBreaker())


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(gc.time, "sleep", lambda s: recorded.append(s))
    return recorded


# ─── Classification ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_server_errors_are_retryable(code):
    assert gc._is_retryable(_APIError(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retryable(code):
    """Retrying a bad key or a malformed request only delays discovering the bug."""
    assert not gc._is_retryable(_APIError(code))


def test_transport_errors_are_retryable():
    assert gc._is_retryable(TimeoutError("read timeout"))
    assert gc._is_retryable(ConnectionError("reset"))


# ─── RetryInfo parsing ──────────────────────────────────────────────────────

def test_server_requested_delay_is_parsed_from_structured_details():
    assert gc._server_requested_delay(_APIError(429, _retry_info("47s"))) == 47.0


def test_server_requested_delay_absent_when_no_retry_info():
    assert gc._server_requested_delay(_APIError(429, {"error": {"code": 429}})) is None
    assert gc._server_requested_delay(TimeoutError()) is None


# ─── The retry loop actually runs ───────────────────────────────────────────

def test_retry_loop_executes_and_eventually_succeeds(sleeps):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _APIError(429, _retry_info("2s"))
        return "ok"

    assert gc._execute_with_retry(flaky, description="test") == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2, "must actually back off between attempts"


def test_server_delay_is_preferred_over_own_backoff(sleeps):
    def always_429():
        raise _APIError(429, _retry_info("10s"))

    with pytest.raises(gc.LLMUnavailableError):
        gc._execute_with_retry(always_429, description="test")

    # 10s + 0.5s margin, capped at max_delay_seconds.
    assert all(s == pytest.approx(10.5) for s in sleeps), sleeps


def test_backoff_is_capped(sleeps, monkeypatch):
    monkeypatch.setattr(gc, "retry_config", lambda: {
        "max_attempts": 4, "base_delay_seconds": 1.0, "max_delay_seconds": 5.0,
        "retryable_status_codes": [429, 500, 502, 503, 504],
    })

    def always_429():
        raise _APIError(429, _retry_info("999s"))

    with pytest.raises(gc.LLMUnavailableError):
        gc._execute_with_retry(always_429, description="test")
    assert all(s <= 5.0 for s in sleeps), sleeps


def test_non_retryable_fails_immediately_without_sleeping(sleeps):
    calls = {"n": 0}

    def bad_request():
        calls["n"] += 1
        raise _APIError(400)

    with pytest.raises(gc.LLMUnavailableError) as exc:
        gc._execute_with_retry(bad_request, description="test")

    assert calls["n"] == 1
    assert sleeps == []
    assert exc.value.last_status == 400


def test_exhausted_attempts_raise_llm_unavailable(sleeps):
    def always_down():
        raise _APIError(503)

    with pytest.raises(gc.LLMUnavailableError) as exc:
        gc._execute_with_retry(always_down, description="test")
    assert exc.value.attempts == gc.retry_config()["max_attempts"]


# ─── Circuit breaker ────────────────────────────────────────────────────────

def test_circuit_opens_after_repeated_failures(sleeps, monkeypatch):
    monkeypatch.setattr(gc, "circuit_breaker_config", lambda: {
        "failure_threshold": 2, "cooldown_seconds": 60,
    })
    monkeypatch.setattr(gc, "_breaker", gc._CircuitBreaker())

    def always_down():
        raise _APIError(503)

    for _ in range(2):
        with pytest.raises(gc.LLMUnavailableError):
            gc._execute_with_retry(always_down, description="test")

    # Third call must fail fast without touching the API.
    calls = {"n": 0}

    def counted():
        calls["n"] += 1
        return "ok"

    with pytest.raises(gc.CircuitOpenError):
        gc._execute_with_retry(counted, description="test")
    assert calls["n"] == 0, "open circuit must not call the API"


def test_success_resets_the_breaker():
    b = gc._CircuitBreaker()
    b.record_failure()
    b.record_success()
    b.check()  # must not raise


# ─── Rate governor ──────────────────────────────────────────────────────────

def test_governor_admits_up_to_rpm_without_waiting(monkeypatch):
    monkeypatch.setattr(gc, "model_limits", lambda m: {"rpm": 3, "tpm": 10**9, "rpd": 100})
    g = gc.RateGovernor()
    for _ in range(3):
        assert g.acquire("m", est_tokens=1) == 0.0


def test_governor_blocks_once_rpm_is_exhausted(monkeypatch):
    """Drive a fake clock so the wait is observable without real sleeping."""
    monkeypatch.setattr(gc, "model_limits", lambda m: {"rpm": 2, "tpm": 10**9, "rpd": 100})

    clock = {"t": 1000.0}
    slept: list[float] = []
    monkeypatch.setattr(gc.time, "monotonic", lambda: clock["t"])

    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s          # advance so the window eventually clears

    monkeypatch.setattr(gc.time, "sleep", fake_sleep)

    g = gc.RateGovernor()
    assert g.acquire("m") == 0.0
    assert g.acquire("m") == 0.0

    waited = g.acquire("m")      # third request exceeds 2 RPM
    assert slept, "governor must wait when the RPM budget is spent"
    assert waited == pytest.approx(60.0, abs=1.0), "should wait for the window to roll"


def test_governor_blocks_when_token_budget_is_spent(monkeypatch):
    monkeypatch.setattr(gc, "model_limits", lambda m: {"rpm": 1000, "tpm": 100, "rpd": 10**6})

    clock = {"t": 500.0}
    slept: list[float] = []
    monkeypatch.setattr(gc.time, "monotonic", lambda: clock["t"])

    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s

    monkeypatch.setattr(gc.time, "sleep", fake_sleep)

    g = gc.RateGovernor()
    g.acquire("m", est_tokens=80)
    g.acquire("m", est_tokens=80)   # would exceed 100 TPM -> must wait
    assert slept, "governor must enforce TPM, not just RPM"


def test_daily_budget_refuses_immediately_rather_than_waiting(monkeypatch):
    """
    The daily window is 24 hours. Blocking on it would look like a hang, so the governor
    raises instead — the caller turns that into an honest not_enough_information verdict.
    """
    monkeypatch.setattr(gc, "model_limits", lambda m: {"rpm": 100, "tpm": 10**9, "rpd": 2})
    slept: list[float] = []
    monkeypatch.setattr(gc.time, "sleep", lambda s: slept.append(s))

    g = gc.RateGovernor()
    g.acquire("m")
    g.acquire("m")
    with pytest.raises(gc.LLMUnavailableError, match="daily request budget"):
        g.acquire("m")
    assert slept == [], "must not wait out a 24h window"


def test_remaining_daily_counts_down(monkeypatch):
    monkeypatch.setattr(gc, "model_limits", lambda m: {"rpm": 100, "tpm": 10**9, "rpd": 3})
    g = gc.RateGovernor()
    assert g.remaining_daily("m") == 3
    g.acquire("m")
    assert g.remaining_daily("m") == 2


def test_configured_rpd_matches_the_measured_quota():
    """
    Observed in a live 429 body: GenerateRequestsPerDayPerProjectPerModel-FreeTier = 20.
    At 4 LLM calls per claim that is five claims per day.
    """
    assert gc.model_limits("gemini-2.5-flash")["rpd"] == 20


def test_configured_rpm_matches_the_measured_quota():
    """
    The audit measured a real limit of 5 RPM for gemini-2.5-flash on free tier. The code
    used to assume 15, admitted 3x the traffic, and 429'd on nearly every call.
    """
    assert gc.model_limits("gemini-2.5-flash")["rpm"] == 5


def test_token_estimate_grows_with_images():
    assert gc.estimate_tokens("x" * 400, image_count=0) == 100
    assert gc.estimate_tokens("x" * 400, image_count=2) == 100 + 2 * 258
