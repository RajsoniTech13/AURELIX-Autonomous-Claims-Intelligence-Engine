"""
The text gateway and its adapters, against recorded-shape fixtures. No network, no keys.

What is pinned here, and why each matters:

* **Each adapter speaks its provider's native structured-output dialect** — strict
  `json_schema` for OpenAI-compatible servers, `output_config.format` for Anthropic, Gemini's
  `response_schema` plus a real system slot — and validates the answer with Pydantic after.
* **Every provider error lands in one vocabulary** (`llm.errors`), built from the SDKs' own
  exception classes rather than message matching.
* **Every attempt is one telemetry record**, with tokens and list-price cost.
* **The ladder is the retry policy**: a failed rung advances, a cached answer makes zero calls.
* **Perception's budget is untouchable**: the Gemini adapter refuses perception's models.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from pydantic import BaseModel

from agent_core.llm import pricing, telemetry
from agent_core.llm.adapters.base import AdapterRequest
from agent_core.llm.adapters.gemini import GeminiAdapter
from agent_core.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from agent_core.llm.errors import (
    AuthError,
    DailyQuotaExhausted,
    InvalidResponse,
    LLMUnavailableError,
    NotConfigured,
    ProviderUnavailable,
    RateLimited,
)
from agent_core.llm.gateway import LLMGateway, PlainText
from agent_core.llm.schema import strict_json_schema
from agent_core.services import gemini_client

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"


class Answer(BaseModel):
    answer: str
    citations: List[str]
    not_found: bool


MESSAGES = [
    {"role": "system", "content": "Answer only from the policy."},
    {"role": "user", "content": "Is the front bumper covered?"},
]


@pytest.fixture(autouse=True)
def _clean_cache_and_governor(monkeypatch):
    gemini_client._inmemory_cache.clear()
    monkeypatch.setattr(gemini_client, "governor", gemini_client.RateGovernor())
    monkeypatch.setattr(gemini_client, "_breaker", gemini_client._CircuitBreaker())
    yield
    gemini_client._inmemory_cache.clear()


# ─── Strict schema ──────────────────────────────────────────────────────────

def test_strict_schema_closes_every_object_and_requires_every_field():
    class Inner(BaseModel):
        clause_id: str
        note: str = ""

    class Outer(BaseModel):
        items: List[Inner]
        flag: bool = False

    schema = strict_json_schema(Outer)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["items", "flag"]
    inner = schema["$defs"]["Inner"]
    assert inner["additionalProperties"] is False
    assert inner["required"] == ["clause_id", "note"]
    assert "default" not in json.dumps(schema).replace('"default"', "")


def test_strict_schema_keeps_a_field_named_title():
    """`title` is a schema keyword *and* a plausible field name; only the keyword goes."""
    class Doc(BaseModel):
        title: str

    schema = strict_json_schema(Doc)
    assert "title" in schema["properties"]
    assert schema["required"] == ["title"]


# ─── Cost math ──────────────────────────────────────────────────────────────

def test_cost_is_list_price_per_million_tokens():
    # gpt-oss-20b on Groq: $0.075 in, $0.30 out, per 1M tokens (config/pricing.yaml).
    assert pricing.cost_usd("groq", "openai/gpt-oss-20b", 1000, 500) == pytest.approx(0.000225)


def test_an_unlisted_model_is_unknown_not_free():
    assert pricing.cost_usd("groq", "no-such-model", 1000, 500) is None


def test_pricing_file_is_dated():
    assert pricing.as_of() is not None


# ─── OpenAI-compatible adapter (Groq, OpenAI) ───────────────────────────────

def _completion(content: str | None = None, finish_reason: str = "stop", refusal: str | None = None):
    from openai.types.chat import ChatCompletion
    body = json.loads((FIXTURES / "groq_chat_completion.json").read_text())
    if content is not None:
        body["choices"][0]["message"]["content"] = content
    body["choices"][0]["finish_reason"] = finish_reason
    body["choices"][0]["message"]["refusal"] = refusal
    return ChatCompletion.model_validate(body)


class StubChat:
    """Stands in for `openai.OpenAI()`; records requests, returns or raises on demand."""

    def __init__(self, result: Any):
        self.result = result
        self.requests: List[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def groq(result) -> tuple[OpenAICompatibleAdapter, StubChat]:
    stub = StubChat(result)
    return OpenAICompatibleAdapter("groq", api_key_env="GROQ_API_KEY", client=stub), stub


def request(**overrides) -> AdapterRequest:
    base = dict(model="openai/gpt-oss-20b", messages=MESSAGES, response_model=Answer,
                max_output_tokens=700, options={"reasoning_effort": "low"})
    base.update(overrides)
    return AdapterRequest(**base)


def test_openai_compatible_sends_a_strict_json_schema_and_validates_the_answer():
    adapter, stub = groq(_completion())
    with telemetry.collect() as records:
        answer = adapter.complete(request())

    assert answer == Answer(answer="Damage to the front bumper is covered for car claims.",
                            citations=["COV-2"], not_found=False)
    sent = stub.requests[0]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert sent["max_completion_tokens"] == 700
    assert sent["reasoning_effort"] == "low"          # config options pass straight through
    assert sent["messages"] == MESSAGES

    assert len(records) == 1
    r = records[0]
    assert (r.provider, r.model, r.outcome) == ("groq", "openai/gpt-oss-20b", "ok")
    assert (r.input_tokens, r.output_tokens) == (1000, 500)
    assert r.cost_usd == pytest.approx(0.000225)


@pytest.mark.parametrize("content,finish,refusal", [
    ('{"answer": "x"}', "stop", None),                 # schema violation
    ("not json at all", "stop", None),                 # not JSON
    ('{"answer": "x", "citat', "length", None),        # truncated
    (None, "stop", "I can't help with that."),         # refusal
])
def test_an_unusable_answer_is_invalid_response_never_a_guess(content, finish, refusal):
    adapter, _ = groq(_completion(content=content or "", finish_reason=finish, refusal=refusal))
    with telemetry.collect() as records, pytest.raises(InvalidResponse):
        adapter.complete(request())
    assert [r.outcome for r in records] == ["invalid_response"]


def _openai_status(cls, status: int, message: str = "error", headers: dict | None = None):
    import httpx
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=req, headers=headers or {}), body=None)


def _openai_errors():
    import httpx
    import openai
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return [
        (_openai_status(openai.RateLimitError, 429, "Rate limit reached on requests per minute (RPM)",
                        {"retry-after": "7"}), RateLimited, "rate_limited"),
        (_openai_status(openai.RateLimitError, 429, "Rate limit reached on requests per day (RPD)"),
         DailyQuotaExhausted, "quota_exhausted"),
        (_openai_status(openai.RateLimitError, 429, "slow down", {"retry-after": "3600"}),
         DailyQuotaExhausted, "quota_exhausted"),
        (_openai_status(openai.AuthenticationError, 401), AuthError, "auth_error"),
        (_openai_status(openai.PermissionDeniedError, 403), AuthError, "auth_error"),
        (_openai_status(openai.InternalServerError, 503), ProviderUnavailable, "unavailable"),
        (openai.APITimeoutError(request=req), ProviderUnavailable, "unavailable"),
        (openai.APIConnectionError(request=req), ProviderUnavailable, "unavailable"),
    ]


@pytest.mark.parametrize("index", range(8))
def test_openai_errors_map_onto_one_vocabulary(index):
    exc, expected, outcome = _openai_errors()[index]
    adapter, _ = groq(exc)
    with telemetry.collect() as records, pytest.raises(expected) as raised:
        adapter.complete(request())
    assert isinstance(raised.value, LLMUnavailableError)   # still catchable the old way
    assert [r.outcome for r in records] == [outcome]
    assert records[0].error_type == type(exc).__name__


def test_without_a_key_the_adapter_is_unavailable_and_refuses_to_build(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    adapter = OpenAICompatibleAdapter("groq", api_key_env="GROQ_API_KEY")
    assert adapter.available() is False
    with pytest.raises(NotConfigured):
        adapter.complete(request())


# ─── Anthropic adapter (optional SDK) ───────────────────────────────────────

def _anthropic_message(stop_reason: str = "end_turn", text: str | None = None):
    pytest.importorskip("anthropic")
    from anthropic.types.beta import BetaMessage
    body = json.loads((FIXTURES / "anthropic_message.json").read_text())
    body["stop_reason"] = stop_reason
    if text is not None:
        body["content"][0]["text"] = text
    return BetaMessage.model_validate(body)


class StubAnthropic:
    def __init__(self, result: Any):
        self.result = result
        self.requests: List[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_anthropic_uses_native_structured_output_with_refusal_fallbacks():
    from agent_core.llm.adapters.anthropic import FALLBACK_BETA, AnthropicAdapter
    stub = StubAnthropic(_anthropic_message())
    adapter = AnthropicAdapter(client=stub)
    with telemetry.collect() as records:
        answer = adapter.complete(request(model="claude-opus-5-5", options=None))

    assert answer.citations == ["COV-2"]
    sent = stub.requests[0]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert sent["fallbacks"] == "default" and sent["betas"] == [FALLBACK_BETA]
    # The system prompt travels in its own parameter, never as a message.
    assert sent["system"] == "Answer only from the policy."
    assert all(m["role"] != "system" for m in sent["messages"])
    assert records[0].cost_usd == pytest.approx((1000 * 4.00 + 500 * 20.00) / 1e6)


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_anthropic_refusal_or_truncation_is_invalid_response(stop_reason):
    from agent_core.llm.adapters.anthropic import AnthropicAdapter
    adapter = AnthropicAdapter(client=StubAnthropic(_anthropic_message(stop_reason)))
    with pytest.raises(InvalidResponse):
        adapter.complete(request(model="claude-opus-5-5", options=None))


def test_anthropic_rate_limit_maps_to_rate_limited():
    anthropic = pytest.importorskip("anthropic")
    import httpx2
    from agent_core.llm.adapters.anthropic import AnthropicAdapter
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.RateLimitError("rate limited", response=httpx2.Response(429, request=req), body=None)
    adapter = AnthropicAdapter(client=StubAnthropic(exc))
    with pytest.raises(RateLimited):
        adapter.complete(request(model="claude-opus-5-5", options=None))


# ─── Gemini adapter (through the existing client) ───────────────────────────

class FakeGenAI:
    """Stands in for `genai.Client()`: `client.models.generate_content(...)`."""

    def __init__(self, text: str = "", error: BaseException | None = None):
        self.calls: List[dict] = []
        self.text, self.error = text, error
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        usage = SimpleNamespace(prompt_token_count=1000, candidates_token_count=400,
                                thoughts_token_count=100)
        return SimpleNamespace(text=self.text, usage_metadata=usage)


ANSWER_JSON = json.dumps({"answer": "Covered.", "citations": ["COV-2"], "not_found": False})


def test_gemini_text_goes_through_the_existing_client_with_a_real_system_slot(monkeypatch):
    fake = FakeGenAI(text=ANSWER_JSON)
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake)
    with telemetry.collect() as records:
        answer = GeminiAdapter().complete(request(model="gemini-2.5-flash-lite", options=None))

    assert answer.citations == ["COV-2"]
    config = fake.calls[0]["config"]
    assert config.system_instruction == "Answer only from the policy."
    assert config.max_output_tokens == 700
    assert "Answer only from the policy." not in fake.calls[0]["contents"]
    # Thinking tokens are billed as output, so they are counted as output.
    assert (records[0].input_tokens, records[0].output_tokens) == (1000, 500)
    assert gemini_client._quota_ledger.spent_today("gemini-2.5-flash-lite") == 1


@pytest.mark.parametrize("model", ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"])
def test_gemini_adapter_refuses_perception_models_without_a_call(monkeypatch, model):
    fake = FakeGenAI(text=ANSWER_JSON)
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake)
    with pytest.raises(NotConfigured):
        GeminiAdapter().complete(request(model=model, options=None))
    assert fake.calls == []
    assert gemini_client._quota_ledger.spent_today(model) == 0


def test_gemini_schema_violation_is_invalid_response(monkeypatch):
    monkeypatch.setattr(gemini_client, "_get_client", lambda: FakeGenAI(text='{"answer": 1}'))
    with pytest.raises(InvalidResponse):
        GeminiAdapter().complete(request(model="gemini-2.5-flash-lite", options=None))


def test_gemini_rate_limit_is_rate_limited(monkeypatch):
    class Err(Exception):
        code = 429
    monkeypatch.setattr(gemini_client, "retry_config", lambda: {
        "max_attempts": 1, "base_delay_seconds": 0, "max_delay_seconds": 0,
        "retryable_status_codes": [429, 500, 502, 503, 504]})
    monkeypatch.setattr(gemini_client, "_get_client", lambda: FakeGenAI(error=Err("429 PerMinute")))
    with pytest.raises(RateLimited):
        GeminiAdapter().complete(request(model="gemini-2.5-flash-lite", options=None))


# ─── Gateway: ladder, cache, failure ────────────────────────────────────────

class ScriptedAdapter:
    """An adapter whose behaviour per call is scripted: an exception or an answer."""

    def __init__(self, provider: str, *outcomes: Any, available: bool = True):
        self.provider = provider
        self.outcomes = list(outcomes)
        self.calls = 0
        self._available = available

    def available(self) -> bool:
        return self._available

    def complete(self, req: AdapterRequest):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            telemetry.record_call(provider=self.provider, model=req.model, outcome="rate_limited")
            raise outcome
        telemetry.record_call(provider=self.provider, model=req.model,
                              input_tokens=1000, output_tokens=500, latency_ms=42)
        return req.response_model.model_validate(outcome)


TASKS = {"copilot_answer": {
    "prompt_version": "copilot-v1", "max_output_tokens": 700,
    "ladder": [{"provider": "groq", "model": "openai/gpt-oss-20b"},
               {"provider": "gemini", "model": "gemini-2.5-flash-lite"}],
}}
GOOD = {"answer": "Covered.", "citations": ["COV-2"], "not_found": False}


def test_a_failed_rung_advances_to_the_next_and_the_attempt_is_recorded():
    first = ScriptedAdapter("groq", RateLimited("slow down"))
    second = ScriptedAdapter("gemini", GOOD)
    gw = LLMGateway(adapters={"groq": first, "gemini": second}, tasks=TASKS)

    with telemetry.collect() as records:
        result = gw.complete("copilot_answer", MESSAGES, Answer)

    assert result.parsed.citations == ["COV-2"]
    assert (result.provider, result.model) == ("gemini", "gemini-2.5-flash-lite")
    assert result.attempts == [{"provider": "groq", "model": "openai/gpt-oss-20b", "result": "RateLimited"}]
    assert (result.input_tokens, result.output_tokens, result.latency_ms) == (1000, 500, 42)
    assert {r.task for r in records} == {"copilot_answer"}
    assert {r.prompt_version for r in records} == {"copilot-v1"}


def test_a_cache_hit_makes_zero_model_calls():
    adapter = ScriptedAdapter("groq", GOOD)
    gw = LLMGateway(adapters={"groq": adapter}, tasks=TASKS)
    gw.complete("copilot_answer", MESSAGES, Answer)

    with telemetry.collect() as records:
        again = gw.complete("copilot_answer", MESSAGES, Answer)

    assert adapter.calls == 1
    assert again.cache_hit is True and again.cost_usd == 0.0
    assert again.parsed.citations == ["COV-2"]
    assert [(r.provider, r.cache_hit) for r in records] == [("cache", True)]


def test_a_different_question_is_not_a_cache_hit():
    adapter = ScriptedAdapter("groq", GOOD, GOOD)
    gw = LLMGateway(adapters={"groq": adapter}, tasks=TASKS)
    gw.complete("copilot_answer", MESSAGES, Answer)
    gw.complete("copilot_answer", MESSAGES[:1] + [{"role": "user", "content": "Is the roof covered?"}], Answer)
    assert adapter.calls == 2


def test_no_configured_provider_is_not_configured_and_spends_nothing():
    gw = LLMGateway(adapters={"groq": ScriptedAdapter("groq", available=False)}, tasks=TASKS)
    with telemetry.collect() as records, pytest.raises(NotConfigured):
        gw.complete("copilot_answer", MESSAGES, Answer)
    assert records == []


def test_every_rung_out_of_quota_is_daily_quota_exhausted():
    gw = LLMGateway(adapters={
        "groq": ScriptedAdapter("groq", DailyQuotaExhausted("groq spent")),
        "gemini": ScriptedAdapter("gemini", DailyQuotaExhausted("gemini spent")),
    }, tasks=TASKS)
    with pytest.raises(DailyQuotaExhausted):
        gw.complete("copilot_answer", MESSAGES, Answer)


def test_plain_text_tasks_unwrap_to_a_string():
    gw = LLMGateway(adapters={"groq": ScriptedAdapter("groq", {"text": "hello"})}, tasks=TASKS)
    assert gw.complete("copilot_answer", MESSAGES).parsed == "hello"


def test_an_unknown_task_is_a_programming_error():
    with pytest.raises(ValueError):
        LLMGateway(adapters={}, tasks=TASKS).complete("no_such_task", MESSAGES)


def test_the_shipped_config_routes_copilot_to_free_tiers_only():
    """Groq free tier first, a non-perception Gemini model second; paid rungs commented out."""
    gw = LLMGateway(adapters={})
    ladder = gw.task_config("copilot_answer")["ladder"]
    assert [r["provider"] for r in ladder] == ["groq", "gemini"]
    from agent_core.services.config import model_config
    assert not {r["model"] for r in ladder} & set(model_config()["chain"])
