"""
AURELIX agent core.

`analyse_claim` is the single public way to analyse one claim. It runs the batched
multimodal pipeline — one LLM call for perception, then deterministic judgement.

The old `process_claim` export is **gone on purpose**. It ran the superseded ten-node graph
at four LLM calls per claim and let the model produce the fraud score and the verdict.
Removing the export is the guardrail: there is no import of `agent_core` that reaches the
old flow by accident, which is what `tests/test_backend_pipeline.py` asserts.
"""
from agent_core.service import ClaimAnalysis, analyse_claim, analyse_claim_events

__all__ = ["analyse_claim", "analyse_claim_events", "ClaimAnalysis"]
