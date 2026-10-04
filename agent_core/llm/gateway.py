"""
LLMGateway — one call signature for every text task, whichever provider serves it.

    gateway.complete("copilot_answer", messages, response_model=CopilotAnswer)
        -> GatewayResult(parsed, provider, model, input/output tokens, latency_ms,
                         cost_usd, cache_hit)

**Routing is configuration.** `config/limits.yaml` → `text_tasks` gives each task a prompt
version, an output-token cap, and a *ladder*: an ordered list of `{provider, model}` rungs.
The gateway tries them in order and returns the first usable answer. On free tiers the
ladder is also the retry policy — a rung that is rate-limited, out of daily quota,
misconfigured, down, or answers badly is skipped in favour of the next, rather than
retried against a budget that is already spent.

**Caching.** The same task, prompt version and messages produce the same answer, so a
repeated question is served from the cache with zero model calls. The cache store is the
one `gemini_client` already uses (in-process, or Redis when `REDIS_URL` is set), not a
second implementation.

**What the gateway never does:** decide a claim. It answers text questions. Verdicts, fraud
scores and confidence remain deterministic Python in `rules_engine.py`, and nothing here is
imported by the claim pipeline.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agent_core.llm import telemetry
from agent_core.llm.adapters.anthropic import AnthropicAdapter
from agent_core.llm.adapters.base import Adapter, AdapterRequest, Message
from agent_core.llm.adapters.gemini import GeminiAdapter
from agent_core.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from agent_core.llm.errors import DailyQuotaExhausted, LLMUnavailableError, NotConfigured
from agent_core.services import gemini_client
from agent_core.services.config import text_providers_config, text_tasks_config

logger = logging.getLogger("aurelix.gateway")


class PlainText(BaseModel):
    """The wrapper used when a caller asks for text: every provider still returns JSON."""
    text: str


@dataclass
class GatewayResult:
    parsed: Union[BaseModel, str]
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: Optional[float] = None
    cache_hit: bool = False
    # Rungs that were skipped or failed before this answer, for the audit trail.
    attempts: List[Dict[str, str]] = field(default_factory=list)


def build_adapters(providers: Optional[Dict[str, Any]] = None) -> Dict[str, Adapter]:
    """One adapter per configured provider. Construction makes no network call."""
    cfg = providers if providers is not None else text_providers_config()
    adapters: Dict[str, Adapter] = {"gemini": GeminiAdapter()}
    for name in ("groq", "openai"):
        if name in cfg:
            adapters[name] = OpenAICompatibleAdapter(
                name,
                api_key_env=cfg[name]["api_key_env"],
                base_url=cfg[name].get("base_url"),
                timeout_seconds=float(cfg[name].get("timeout_seconds", 30)),
            )
    if "anthropic" in cfg:
        adapters["anthropic"] = AnthropicAdapter(
            api_key_env=cfg["anthropic"]["api_key_env"],
            timeout_seconds=float(cfg["anthropic"].get("timeout_seconds", 60)),
        )
    return adapters


class LLMGateway:
    def __init__(
        self,
        adapters: Optional[Dict[str, Adapter]] = None,
        tasks: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ):
        self.adapters = adapters if adapters is not None else build_adapters()
        self.tasks = tasks if tasks is not None else text_tasks_config()
        self.use_cache = use_cache

    def task_config(self, task: str) -> Dict[str, Any]:
        if task not in self.tasks:
            raise ValueError(f"unknown text task {task!r}; configured: {sorted(self.tasks)}")
        return self.tasks[task]

    def available_providers(self, task: str) -> List[str]:
        """Rungs that could be attempted right now. Makes no call."""
        out = []
        for rung in self.task_config(task)["ladder"]:
            adapter = self.adapters.get(rung["provider"])
            if adapter is not None and adapter.available():
                out.append(f"{rung['provider']}/{rung['model']}")
        return out

    @staticmethod
    def _cache_key(task: str, cfg: Dict[str, Any], messages: List[Message], schema: str) -> str:
        """Everything that can change the answer is in the key; nothing else is."""
        payload = json.dumps(
            {"task": task, "prompt_version": cfg.get("prompt_version"),
             "ladder": cfg.get("ladder"), "schema": schema, "messages": messages},
            sort_keys=True,
        )
        return "gateway:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete(
        self,
        task: str,
        messages: List[Message],
        response_model: Optional[Type[BaseModel]] = None,
    ) -> GatewayResult:
        """
        Answer one text task. Raises an `llm.errors` type when no rung could answer:
        `NotConfigured` if none could even be tried, otherwise the last failure's class.
        """
        cfg = self.task_config(task)
        model_cls = response_model or PlainText
        unwrap = response_model is None

        with telemetry.call_context(task=task, prompt_version=cfg.get("prompt_version")):
            key = self._cache_key(task, cfg, messages, model_cls.__name__)
            if self.use_cache:
                cached = gemini_client._cache_get(key)
                if cached:
                    parsed = model_cls.model_validate_json(cached)
                    telemetry.record_call(provider="cache", model="cache", cache_hit=True)
                    return GatewayResult(
                        parsed=parsed.text if unwrap else parsed,
                        provider="cache", model="cache", cost_usd=0.0, cache_hit=True,
                    )

            attempts: List[Dict[str, str]] = []
            last_error: Optional[LLMUnavailableError] = None

            for rung in cfg["ladder"]:
                provider, model = rung["provider"], rung["model"]
                adapter = self.adapters.get(provider)
                if adapter is None or not adapter.available():
                    attempts.append({"provider": provider, "model": model, "result": "not_configured"})
                    continue
                request = AdapterRequest(
                    model=model, messages=messages, response_model=model_cls,
                    max_output_tokens=int(cfg.get("max_output_tokens", 800)),
                    options=dict(rung.get("options") or {}),
                )
                with telemetry.collect() as records:
                    try:
                        parsed = adapter.complete(request)
                    except NotConfigured as exc:
                        attempts.append({"provider": provider, "model": model, "result": "not_configured"})
                        logger.info("[Gateway] %s/%s skipped: %s", provider, model, exc)
                        continue
                    except LLMUnavailableError as exc:
                        attempts.append({"provider": provider, "model": model,
                                         "result": type(exc).__name__})
                        logger.warning("[Gateway] %s/%s failed (%s); next rung",
                                       provider, model, type(exc).__name__)
                        last_error = exc
                        continue

                final = records[-1] if records else None
                if self.use_cache:
                    gemini_client._cache_set(
                        key, parsed.model_dump_json(),
                        ttl_seconds=int(cfg.get("cache_ttl_seconds", 3600)),
                    )
                return GatewayResult(
                    parsed=parsed.text if unwrap else parsed,
                    provider=provider, model=model,
                    input_tokens=final.input_tokens if final else 0,
                    output_tokens=final.output_tokens if final else 0,
                    latency_ms=final.latency_ms if final else 0,
                    cost_usd=final.cost_usd if final else None,
                    attempts=attempts,
                )

        summary = ", ".join(f"{a['provider']}/{a['model']}={a['result']}" for a in attempts) or "none"
        if last_error is None:
            raise NotConfigured(f"no provider is configured for task {task!r} (tried {summary})")
        if isinstance(last_error, DailyQuotaExhausted):
            raise DailyQuotaExhausted(f"{task}: every provider is out of daily quota ({summary})")
        raise type(last_error)(f"{task}: no provider could answer ({summary})") from last_error


@lru_cache(maxsize=1)
def default_gateway() -> LLMGateway:
    """The process-wide gateway, built from config on first use."""
    return LLMGateway()
