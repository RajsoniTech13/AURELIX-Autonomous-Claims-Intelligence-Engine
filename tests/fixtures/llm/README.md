# LLM response fixtures

Response bodies in each provider's documented wire format, used by
`tests/test_llm_gateway.py` so adapter tests never touch the network.

These were written by hand from the providers' API documentation, **not captured from live
traffic** — no API key or quota was spent producing them. What keeps them honest is that
each test parses them through the provider SDK's own response model first
(`openai.types.chat.ChatCompletion`, `anthropic.types.beta.BetaMessage`): a fixture that
drifted from the real shape would fail validation there, before the adapter ever saw it.
