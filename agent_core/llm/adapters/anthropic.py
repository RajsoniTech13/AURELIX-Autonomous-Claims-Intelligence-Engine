"""
Anthropic (Claude), as an optional adapter. Off unless `ANTHROPIC_API_KEY` is set *and*
the optional `anthropic` package is installed (`requirements-optional.txt`).

Why it exists in a free-tier project at all: to show the gateway is genuinely
provider-agnostic, and so a deployment that does have a key can route a task to Claude by
editing `config/limits.yaml`. Nothing in the free deploy uses it, and its absence costs
nothing — `available()` is false and the gateway skips the rung.

**Structured output** uses the Messages API's native `output_config.format` with a JSON
schema. The provider constrains decoding to the schema; the answer is then validated
against the Pydantic model regardless.

**Refusals.** A request can be declined by safety classifiers with HTTP 200 and
`stop_reason: "refusal"`. The adapter opts into server-side `fallbacks: "default"`, which
re-runs a declined request on Anthropic's recommended fallback model inside the same call,
and still checks `stop_reason` afterwards — a refusal is an `InvalidResponse`, never an
answer.

Not exercised against the live API in this project (no key, no budget). Its contract is
pinned by tests against a stub client and the real SDK's exception classes.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from agent_core.llm import telemetry
from agent_core.llm.adapters.base import AdapterRequest, split_system
from agent_core.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from agent_core.llm.errors import (
    AuthError,
    InvalidResponse,
    LLMUnavailableError,
    NotConfigured,
    ProviderUnavailable,
    RateLimited,
)
from agent_core.llm.schema import strict_json_schema

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicAdapter:
    provider = "anthropic"

    def __init__(self, *, api_key_env: str = "ANTHROPIC_API_KEY",
                 timeout_seconds: float = 60.0, client: Any = None):
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds
        self._client = client

    def available(self) -> bool:
        if self._client is not None:
            return True
        if not os.getenv(self.api_key_env):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.available():
                raise NotConfigured(
                    f"anthropic: {self.api_key_env} is not set or the optional "
                    f"`anthropic` package is not installed"
                )
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=os.environ[self.api_key_env],
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        return self._client

    @staticmethod
    def _map_error(exc: Exception) -> LLMUnavailableError:
        import anthropic
        if isinstance(exc, anthropic.RateLimitError):
            return RateLimited(f"anthropic: rate limited: {exc}")
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return AuthError(f"anthropic: credentials rejected ({exc.status_code})")
        if isinstance(exc, anthropic.APIConnectionError):   # includes APITimeoutError
            return ProviderUnavailable(f"anthropic: connection failed: {exc}")
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderUnavailable(f"anthropic: HTTP {exc.status_code}: {exc}")
        return ProviderUnavailable(f"anthropic: {type(exc).__name__}: {exc}")

    def complete(self, request: AdapterRequest) -> BaseModel:
        client = self._get_client()
        system, rest = split_system(request.messages)
        started = time.perf_counter()
        usage = None

        def finish(outcome: str, error: Optional[BaseException] = None) -> None:
            telemetry.record_call(
                provider=self.provider, model=request.model, outcome=outcome,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_type=type(error).__name__ if error is not None else None,
            )

        try:
            response = client.beta.messages.create(
                model=request.model,
                max_tokens=request.max_output_tokens,
                system=system or anthropic_omit(),
                messages=rest,
                output_config={"format": {
                    "type": "json_schema",
                    "schema": strict_json_schema(request.response_model),
                }},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except Exception as exc:  # noqa: BLE001 - translated immediately
            error = self._map_error(exc)
            finish(OpenAICompatibleAdapter._outcome(error), exc)
            raise error from exc

        usage = getattr(response, "usage", None)
        if response.stop_reason == "refusal":
            error = InvalidResponse("anthropic: the request was declined")
            finish(telemetry.INVALID_RESPONSE, error)
            raise error
        if response.stop_reason == "max_tokens":
            error = InvalidResponse("anthropic: output truncated at max tokens")
            finish(telemetry.INVALID_RESPONSE, error)
            raise error

        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        try:
            parsed = request.response_model.model_validate_json(text)
        except ValidationError as exc:
            error = InvalidResponse("anthropic: response failed schema validation")
            finish(telemetry.INVALID_RESPONSE, exc)
            raise error from exc

        finish(telemetry.OK)
        return parsed


def anthropic_omit() -> Any:
    """The SDK's sentinel for "parameter not sent", so an empty system prompt is omitted."""
    import anthropic
    return anthropic.omit
