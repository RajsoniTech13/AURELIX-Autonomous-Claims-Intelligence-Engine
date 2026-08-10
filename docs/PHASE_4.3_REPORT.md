# Phase 4.3 — Guardrails on the migration

The 4.2 migration was only as durable as the promise not to undo it. This phase turns that
promise into tests, then deletes the code the promise was about.

**Cost: 0 Gemini requests.** Everything here is hermetic.

| | before | after |
|---|---:|---:|
| Tests | 159 | **172** |
| Lines of superseded pipeline on disk | 977 | **0** |
| Guarantees enforced by test | 0 | **3, independent** |

---

## 1. What changed

| file | change |
|---|---|
| `tests/test_backend_pipeline.py` | **new** — 14 guardrail tests |
| `agent_core/orchestrator/graph.py` | **deleted** (571 lines) |
| `agent_core/agents/{claim_ingestion,vision_analysis,fraud_review,decision}.py` | **deleted** (290 lines) |
| `agent_core/output_mapper.py` | **deleted** (115 lines) |
| `test_graph.py` (repo root) | **deleted** |
| `agent_core/services/config.py`, `config/limits.yaml` | removed `allow_text_only_inference` |
| `tests/test_{pipeline,output_contract,no_fabrication}.py` | ported off the deleted modules |

---

## 2. Three guarantees, deliberately independent

Any single check is escapable, so none of them stands alone.

### 2.1 Static reachability

An AST walk of the transitive first-party import graph from `platform_backend.main`,
asserting no edge reaches the superseded modules. **Function-level imports are included**,
and that is the whole point: the pre-migration backend reached the old router with

```python
from agent_core.orchestrator.graph import route_after_validation
```

written in the middle of a generator, where no top-of-file scan would ever have found it.

One subtlety worth recording. The first draft resolved module names to files and skipped
anything unresolvable as "third-party". Since the superseded modules are now *deleted*, that
version would have quietly ignored an import of `agent_core.orchestrator.graph` and reported
the graph as unreachable while the code plainly referenced it — a guardrail that passes
because its target is missing is not a guardrail. First-party names are now recorded whether
or not a file backs them.

Paired with an inverse assertion (`agent_core.service` **is** reachable), so the test cannot
pass on a backend that imports nothing, and with a subprocess check on `sys.modules` in a
clean interpreter in case the static scan and the import machinery ever disagree.

### 2.2 Call count

A spy on `call_gemini_multimodal` asserts:

- one claim with a usable image → **exactly 1** request;
- one claim with no usable image → **exactly 0** (preflight short-circuit);
- a model that cannot be reached → `not_enough_information` + `R002_perception_unavailable`,
  never a verdict.

Four is the number this must never be again: at four calls per claim the 44-case benchmark
needs 176 requests against a free budget of 20, which is not slow, it is arithmetically
impossible. The backend's own `execute_claim_sync` is exercised too, not just the
`agent_core` entry point, so the route's path is covered rather than assumed.

### 2.3 Stage identity

The stages that actually run are compared against the declared `PIPELINE_STAGES`; exactly
one of them is in `LLM_STAGES`; a skipped perception reports `skipped` rather than
`complete`; and the audit trail names the same six stages. The frontend keeps its own copy
of the stage list, so that copy is **read out of the .tsx source and compared** — a UI that
silently stops lighting up is the most likely way this drifts.

---

## 3. Verifying that the guardrails bite

A test that cannot fail is worse than no test, so the primary one was mutated. The
superseded import was planted back into `claim_service.py` in exactly its historical shape —
inside a function body:

```
$ ./venv/bin/python -m pytest tests/test_backend_pipeline.py -q
F.............
FAILED test_fastapi_app_cannot_reach_the_superseded_flow
E   AssertionError: platform_backend.main can reach the superseded four-call pipeline
E   via ['agent_core.orchestrator.graph']. The web platform must use agent_core.service only.
```

Reverted; suite green again. The mutation is not committed.

---

## 4. Deleting the old pipeline

977 lines removed. Unreachable is good, absent is better: an unreachable module is one
careless import away from being reachable again, and `test_superseded_modules_do_not_exist_on_disk`
now pins that.

**The tests that covered them were ported, not dropped.** Their intent survives at the
boundary that still exists:

| was | now |
|---|---|
| `output_mapper` never raises on partial graph state | `to_output_row` produces a complete valid row for every degenerate entry |
| `vision_analysis.cannot_assess` returns `unknown`, not `none` | an unassessable claim reaches the **CSV** as `unknown` — which is where it actually matters |
| `route_after_validation` short-circuits unusable evidence | `preflight` refuses it, and the zero-request consequence is asserted end to end |
| injection flag reaches the output row | same assertion, built from a `ClaimPerception` |

One assertion was **retired rather than ported**: `test_output_mapper_only_reads_keys_the_graph_declares`,
the P0-1 regression test. It guarded against reading keys off an untyped state dict that no
longer exists — `judge` returns a fixed shape and `to_output_row` consumes it. The bug class
is structurally impossible, and keeping a test that cannot fail would misrepresent coverage.

### `allow_text_only_inference` removed

The batched pipeline never consulted it. It had been a configuration knob that silently did
nothing since Phase 2 — worse than no knob, because it reads as a supported capability. Its
purpose, inferring damage from a filename when no image loads, is precisely the behaviour
the no-fabrication rule forbids and precisely how the pre-Phase-0.5 pipeline produced 44
rows of hallucinated damage. Removed rather than reconnected.

---

## 5. What I verified, with output

```
$ ./venv/bin/python -m pytest
172 passed in 1.16s

$ ./venv/bin/python -m pytest tests/test_backend_pipeline.py -v
collected 14 items
tests/test_backend_pipeline.py ..............                            [100%]
14 passed in 0.84s
```

The benchmark is unchanged by the refactor — `judge` and `to_output_row` moved modules, so
this had to be confirmed rather than assumed:

```
$ ./venv/bin/python -m agent_core.run_pipeline
Wrote agent_core/output/output.csv  (44 rows)
Quota after run: gemini-3.6-flash: 18/20      <- unchanged, zero requests

$ ./venv/bin/python -m agent_core.evaluation.evaluate_synthetic
Scored 44/44  accuracy 93.2%  macro-F1 93.2%
```

---

## 6. What I could not verify

- **The frontend stage test reads source, not behaviour.** It parses `INITIAL_STAGES` out of
  the `.tsx` file. If the component stopped using that constant, the test would still pass.
  A rendered end-to-end check needs a browser driver, which this phase does not add.
- **The static scan follows names, not aliases.** `importlib.import_module(some_variable)`
  would evade it. Nothing in the codebase does that, and the runtime `sys.modules` check
  would catch it if the module were imported at startup — but not if it were imported lazily
  inside a request.
- **Concurrency is untested**, unchanged from 4.2.

---

## 7. Risks and tech debt introduced

- **Dead schemas.** `ClaimIngestionOutput`, `VisionAnalysisOutput`, `FraudReviewOutput` and
  `DecisionOutput` remain in `schemas/models.py` with no producer. `test_no_fabrication`
  still exercises two of them for their `from_failure` behaviour. They are inert data
  classes, so leaving them is low-risk, but they are debt and should go with a follow-up
  that ports those two assertions.
- **`agent_core/services/vector_store.py` is now the only remaining piece of the old
  pipeline still wired to anything** — `platform_backend/main.py` calls
  `index_historical_claims` at startup and nothing consumes the result. Task 4.4 replaces it.
- **Two stray root scripts remain** — `test_db_hang.py` and `test_parse.js`. Both are tracked
  debugging scratch files unrelated to this phase; I deleted `test_graph.py` because my own
  change broke it, and left these alone rather than widening the diff. Worth a decision.
- **`SUPERSEDED_MODULES` is a hand-maintained list.** It cannot know about a *new* bad
  pipeline, only the old one. The call-count test is the general guard.

---

## 8. Recommended next

**4.4** — Phase 3 retrieval. `R030_duplicate_image_reuse` is in `decision_rules.yaml` and
nothing can currently make it fire, which means the strongest fraud signal in this domain is
declared and dead. It is also what re-attaches retrieval to a verdict after §7 disconnected
the TF-IDF store.
