"""
Gemini, for text tasks — reusing the existing client rather than wrapping a second one.

`services/gemini_client.py` already owns everything that makes Gemini safe on a 20-request
daily budget: the persisted quota ledger, the per-model rate governor, record-then-refund
accounting, server-directed retry, and the circuit breaker. This adapter calls through it,
so a text task gets all of that for free and none of it is duplicated. It also gets
telemetry for free: the client emits a record for every attempt.

**Perception's budget is off limits.** A model on the perception ladder
(`models.chain` in `config/limits.yaml`) is refused here outright. Perception decides
claims for the public demo; a reviewer asking the copilot questions must never be the
reason a claimant's analysis comes back `not_enough_information`. Text tasks use a model
that perception does not, so the two budgets cannot collide.
"""
from __future__ import annotations

import os

from pydantic import BaseModel

from agent_core.llm import telemetry
from agent_core.llm.adapters.base import AdapterRequest, split_system
from agent_core.llm.errors import (
    AuthError,
    DailyQuotaExhausted,
    InvalidResponse,
    LLMUnavailableError,
    NotConfigured,
    ProviderUnavailable,
    RateLimited,
)
from agent_core.services import gemini_client
from agent_core.services.config import model_config

_BY_OUTCOME = {
    telemetry.RATE_LIMITED: RateLimited,
    telemetry.AUTH_ERROR: AuthError,
    telemetry.INVALID_RESPONSE: InvalidResponse,
}


class GeminiAdapter:
    provider = "gemini"

    def available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    def complete(self, request: AdapterRequest) -> BaseModel:
        if request.model in model_config()["chain"]:
            raise NotConfigured(
                f"{request.model} is on the perception ladder; text tasks may not spend "
                f"perception's daily budget. Configure a different Gemini model."
            )
        if gemini_client.remaining_requests(request.model) <= 0:
            # Known spent: say so without spending a request to rediscover it.
            raise DailyQuotaExhausted(f"{request.model} daily budget already spent", model=request.model)

        system, rest = split_system(request.messages)
        prompt = "\n\n".join(m["content"] for m in rest)
        options = request.options or {}

        with telemetry.collect() as attempts:
            try:
                return gemini_client.call_gemini_text(
                    prompt,
                    request.response_model,
                    model=request.model,
                    temperature=float(options.get("temperature", 0.1)),
                    system_instruction=system or None,
                    max_output_tokens=request.max_output_tokens,
                )
            except DailyQuotaExhausted:
                raise
            except LLMUnavailableError as exc:
                # The client already classified the failed attempt for telemetry; reuse that
                # classification instead of re-parsing the exception chain a second time.
                last = attempts[-1].outcome if attempts else None
                raise _BY_OUTCOME.get(last, ProviderUnavailable)(str(exc)) from exc
