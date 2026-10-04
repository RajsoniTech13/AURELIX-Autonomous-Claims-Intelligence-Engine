"""
The shape every adapter has, so the gateway can treat them interchangeably.

A `Protocol`, not a base class: adapters share no code, only a contract, and inheriting
from an empty base would suggest otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Type

from pydantic import BaseModel

Message = Dict[str, str]
"""`{"role": "system" | "user" | "assistant", "content": str}` — the common denominator."""


@dataclass
class AdapterRequest:
    model: str
    messages: List[Message]
    response_model: Type[BaseModel]
    max_output_tokens: int = 800
    # Provider-specific knobs from config (temperature, reasoning_effort, ...). Passed
    # through only by the adapter that understands them.
    options: Dict[str, Any] | None = None


class Adapter(Protocol):
    provider: str

    def available(self) -> bool:
        """True when a call could be attempted: a key is set and the SDK is importable."""

    def complete(self, request: AdapterRequest) -> BaseModel:
        """
        Make one request and return the validated response model.

        Must raise only `llm.errors` types, and must emit exactly one telemetry record per
        network attempt (via `telemetry.record_call`, or via `gemini_client`, which does it).
        """


def split_system(messages: List[Message]) -> tuple[str, List[Message]]:
    """
    Separate system messages from the conversation.

    Anthropic and Gemini take the system prompt as its own parameter rather than as a
    message, which is the stronger arrangement: operator instructions and user input arrive
    on different channels.
    """
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    rest = [m for m in messages if m.get("role") != "system"]
    return system, rest
