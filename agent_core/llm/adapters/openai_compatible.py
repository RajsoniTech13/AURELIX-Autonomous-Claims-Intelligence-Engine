"""
One adapter for every provider that speaks the OpenAI Chat Completions protocol.

Groq serves its models behind an OpenAI-compatible endpoint
(`https://api.groq.com/openai/v1`), so the official `openai` SDK talks to Groq and to OpenAI
with nothing different but the base URL and the key. Two providers, one adapter, one set
of tests.

**Structured output** uses each server's native mechanism:
`response_format={"type": "json_schema", "json_schema": {"strict": true, ...}}`. With strict
mode the server constrains decoding to the schema. The answer is still validated against
the Pydantic model afterwards — the server's promise is not our check.

**No SDK retries** (`max_retries=0`). The gateway's ladder is the retry policy: on a
free-tier daily limit, retrying the same provider only spends the next request too.

**Groq's 429 has two meanings.** A per-minute limit clears in seconds; a per-day limit does
not clear until tomorrow. Groq's error message names the limit ("requests per day") and its
`retry-after` header gives the wait, so either signal marks the 429 as daily.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, ValidationError

from agent_core.llm import telemetry
from agent_core.llm.adapters.base import AdapterRequest
from agent_core.llm.errors import (
    AuthError,
    DailyQuotaExhausted,
    InvalidResponse,
    LLMUnavailableError,
    NotConfigured,
    ProviderUnavailable,
    RateLimited,
)
from agent_core.llm.schema import strict_json_schema

# A wait longer than this is not a per-minute window.
_DAILY_RETRY_AFTER_SECONDS = 120


def _retry_after(exc: Any) -> Optional[float]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def classify_rate_limit(exc: Any) -> LLMUnavailableError:
    """Per-day or per-minute? See the module docstring."""
    message = str(getattr(exc, "message", "") or exc).lower()
    wait = _retry_after(exc)
    if "per day" in message or (wait is not None and wait > _DAILY_RETRY_AFTER_SECONDS):
        return DailyQuotaExhausted(f"daily limit reached: {exc}")
    return RateLimited(f"rate limited: {exc}")


class OpenAICompatibleAdapter:
    def __init__(
        self,
        provider: str,
        *,
        api_key_env: str,
        base_url: Optional[str] = None,
        timeout_seconds: float = 30.0,
        client: Any = None,
    ):
        self.provider = provider
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self._client = client          # injected in tests; built lazily otherwise

    def available(self) -> bool:
        if self._client is not None:
            return True
        if not os.getenv(self.api_key_env):
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.available():
                raise NotConfigured(f"{self.provider}: {self.api_key_env} is not set")
            import openai
            self._client = openai.OpenAI(
                api_key=os.environ[self.api_key_env],
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        return self._client

    def _map_error(self, exc: Exception) -> LLMUnavailableError:
        """Translate the SDK's exception tree. Typed classes, never message matching."""
        import openai
        if isinstance(exc, openai.RateLimitError):
            return classify_rate_limit(exc)
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return AuthError(f"{self.provider}: credentials rejected ({exc.status_code})")
        if isinstance(exc, openai.APIConnectionError):     # includes APITimeoutError
            return ProviderUnavailable(f"{self.provider}: connection failed: {exc}")
        if isinstance(exc, openai.APIStatusError):
            return ProviderUnavailable(f"{self.provider}: HTTP {exc.status_code}: {exc}")
        return ProviderUnavailable(f"{self.provider}: {type(exc).__name__}: {exc}")

    @staticmethod
    def _outcome(error: LLMUnavailableError) -> str:
        if isinstance(error, DailyQuotaExhausted):
            return telemetry.QUOTA_EXHAUSTED
        if isinstance(error, RateLimited):
            return telemetry.RATE_LIMITED
        if isinstance(error, AuthError):
            return telemetry.AUTH_ERROR
        if isinstance(error, InvalidResponse):
            return telemetry.INVALID_RESPONSE
        return telemetry.UNAVAILABLE

    def complete(self, request: AdapterRequest) -> BaseModel:
        client = self._get_client()
        options: Dict[str, Any] = dict(request.options or {})
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": request.response_model.__name__,
                "strict": True,
                "schema": strict_json_schema(request.response_model),
            },
        }

        started = time.perf_counter()
        usage = None

        def finish(outcome: str, error: Optional[BaseException] = None) -> None:
            telemetry.record_call(
                provider=self.provider, model=request.model, outcome=outcome,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_type=type(error).__name__ if error is not None else None,
            )

        try:
            response = client.chat.completions.create(
                model=request.model,
                messages=request.messages,
                max_completion_tokens=request.max_output_tokens,
                response_format=response_format,
                **options,
            )
        except Exception as exc:  # noqa: BLE001 - translated immediately
            error = self._map_error(exc)
            finish(self._outcome(error), exc)
            raise error from exc

        usage = getattr(response, "usage", None)
        choice = response.choices[0] if response.choices else None
        content = getattr(getattr(choice, "message", None), "content", None)
        refusal = getattr(getattr(choice, "message", None), "refusal", None)

        if choice is None or refusal or not content:
            error = InvalidResponse(f"{self.provider}: empty or refused completion")
            finish(telemetry.INVALID_RESPONSE, error)
            raise error
        if choice.finish_reason == "length":
            # A truncated JSON document is not a short answer, it is a broken one.
            error = InvalidResponse(f"{self.provider}: output truncated at max tokens")
            finish(telemetry.INVALID_RESPONSE, error)
            raise error
        try:
            parsed = request.response_model.model_validate_json(content)
        except ValidationError as exc:
            error = InvalidResponse(f"{self.provider}: response failed schema validation")
            finish(telemetry.INVALID_RESPONSE, exc)
            raise error from exc

        finish(telemetry.OK)
        return parsed
