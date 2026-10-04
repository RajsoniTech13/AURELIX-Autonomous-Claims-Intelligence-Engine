"""
One error vocabulary for every provider.

Each provider SDK has its own exception tree — `openai.RateLimitError`,
`anthropic.RateLimitError`, `google.genai.errors.APIError(code=429)` — and code that caught
those directly would need to know which vendor it was talking to. The gateway exists so
callers do not. Every adapter therefore translates its provider's errors into these five,
and nothing above the adapters ever sees a vendor exception.

They extend the classes `services/gemini_client.py` already defined, rather than starting
a parallel tree, so the existing rule still holds everywhere: catching `LLMUnavailableError`
catches every way a model call can fail.

| class                | meaning                                   | right response          |
|----------------------|-------------------------------------------|-------------------------|
| RateLimited          | per-minute limit hit                      | next provider, or wait  |
| DailyQuotaExhausted  | today's budget is spent                   | next provider, never retry |
| AuthError            | missing or rejected credentials           | next provider; a config bug |
| ProviderUnavailable  | 5xx, timeout, network, request rejected   | next provider           |
| InvalidResponse      | reached the model, answer unusable        | next provider           |

Every row ends in "next provider" because the ladder *is* the retry policy: on free tiers a
second attempt against the same exhausted budget only spends it.
"""
from __future__ import annotations

from agent_core.services.gemini_client import DailyQuotaExhausted, LLMUnavailableError

# A plain alias: "the provider could not serve this" is exactly what the existing class means.
ProviderUnavailable = LLMUnavailableError


class RateLimited(LLMUnavailableError):
    """A per-minute limit. The same provider will work again shortly."""


class AuthError(LLMUnavailableError):
    """Credentials were missing or rejected. Retrying cannot fix it; configuration can."""


class InvalidResponse(LLMUnavailableError):
    """
    The model answered, but not usably: malformed JSON, a schema violation, an empty or
    truncated completion, or a refusal. Never repaired by guessing what it meant.
    """


class NotConfigured(AuthError):
    """
    The adapter cannot even try: no API key, or its optional SDK is not installed.

    Separate from a rejected key because it costs nothing and is expected — the free deploy
    has no OpenAI or Anthropic key on purpose. The gateway skips such a rung without
    recording a call, because no call was made.
    """


__all__ = [
    "AuthError", "DailyQuotaExhausted", "InvalidResponse", "LLMUnavailableError",
    "NotConfigured", "ProviderUnavailable", "RateLimited",
]
