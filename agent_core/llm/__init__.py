"""
The text-LLM layer: one gateway in front of several providers, plus per-call telemetry.

Why this package exists. Until Phase 7 the only model call in AURELIX was perception, and
it went straight to Gemini through `services/gemini_client.py`. The policy copilot adds a
second kind of call — text in, a short structured answer out — and that kind of call can
be served by more than one provider. Writing the copilot against one vendor's SDK would
hard-wire a cost and availability decision into feature code. The gateway keeps that
decision in `config/limits.yaml` (`text_tasks`), where it can change without a deploy of
new logic.

Deliberately empty of imports. `services/gemini_client.py` imports `llm.telemetry`, and
`llm.adapters.gemini` imports `gemini_client`; importing the gateway here would make that
a cycle. Import submodules directly: `from agent_core.llm.gateway import LLMGateway`.
"""
