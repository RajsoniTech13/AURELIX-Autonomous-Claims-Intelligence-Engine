# Phase 0.5 — Stop the bleeding

**Goal:** make the repository run, and make it tell the truth. No architecture work; that
is Phase 1 onward.

All four P0s from `docs/AUDIT.md` are fixed, plus three defects found while fixing them.
74 tests pass. The CLI produces output rows for the first time. And a live run against
real photographs showed the verification core working on the canonical hard case — while
also exposing a quota ceiling that changes the plan.

---

## 1. What changed

### New files

| File | Purpose |
|---|---|
| `agent_core/schemas/contract.py` | The frozen output contract: 14 columns, five closed vocabularies, 1-based image ids, normalisers |
| `agent_core/output_mapper.py` | The single state→CSV mapping (replaces two divergent copies) |
| `agent_core/services/config.py` | Config loader; no quota or retry numbers left in code |
| `config/limits.yaml` | Per-tier RPM/TPM/RPD, retry policy, circuit breaker, evidence policy |
| `tests/test_output_contract.py` | Golden header + vocabulary conformance (22 tests) |
| `tests/test_no_fabrication.py` | The no-fabricated-verdict guarantee (10 tests) |
| `tests/test_resilience.py` | Retry, backoff, governor, breaker (23 tests) |
| `tests/test_pipeline.py` | State-key wiring, evidence handling, injection (19 tests) |
| `tests/fixtures/adversarial_claims.csv` + `tests/fixtures/images/` | 7 adversarial cases against 4 real photographs |
| `.env.example` | Credential template, no values |
| `docs/SECRET_ROTATION.md` | Exposure assessment and rotation steps |

### Rewritten

| File | Change |
|---|---|
| `agent_core/services/gemini_client.py` | Mock fallback deleted; working retry; sliding-window RPM/TPM/RPD governor; circuit breaker; server-directed backoff; full-image content hashing; pooled Redis |
| `agent_core/main.py` | Correct state keys; one mapping function; per-claim checkpointing; CLI flags; loads images from disk |
| `agent_core/agents/image_validator.py` | Verifies files exist and decode; maps issues to the frozen flag vocabulary |
| `agent_core/agents/vision_analysis.py` | Refuses to infer damage without pixels; explicit `cannot_assess` finding |
| `agent_core/prompts/templates.py` | Untrusted-input delimiting; injection detection; `unknown` vs `none` guidance |
| `agent_core/evaluation/evaluate.py` | Fabricated sections removed; coverage reported; join key fixed |

### Edited

`agent_core/schemas/models.py` (Literal enums, `from_failure`), `agent_core/orchestrator/graph.py`
(error propagation, honest short-circuit, `pipeline_errors`), `agent_core/agents/user_risk.py`
(frozen flag vocabulary), `agent_core/agents/fraud_review.py` + `claim_ingestion.py` (untrusted
wrapping), `platform_backend/services/claim_service.py` (state keys, deduplicated routing),
`README.md` (corrected agent count and the Docker claim), `agent_core/README.md` (key removed).

---

## 2. Defects fixed

### P0-1 — CLI wrote an empty file
`main.py` read `quality`, `compliance`, `escalation`; the graph writes `image_validation`,
`policy`, and nothing named `escalation`. Every claim raised `KeyError`, was swallowed, and
skipped. Now one `build_output_row` function reads only keys the graph declares, and
`tests/test_pipeline.py::test_output_mapper_only_reads_keys_the_graph_declares` asserts that
against `ClaimsState.__annotations__` so the two cannot drift apart again.

### P0-2 — Missing images silently became hallucinations
`run_image_validator` returned `valid=True` for declared-but-nonexistent paths. It now
resolves each path against the filesystem and returns `valid=False` with
`missing_file:img_N`. `route_after_validation` short-circuits on `valid`, and
`vision_analysis` returns `cannot_assess(...)` — `severity=unknown`, not `none` — rather
than guessing. Text-only inference survives as an explicit opt-in
(`--allow-text-only`), defaults off, and marks its output `[UNGROUNDED]`.

### P0-3 — Fabricated verdicts
`_get_mock_response` is deleted. `LLMUnavailableError` propagates to the decision node,
which emits `DecisionOutput.from_failure(...)`: `not_enough_information`, confidence 0,
`manual_review_required=True`, carrying the real error. An AST-based test asserts the client
module contains no `supported`/`contradicted` literal in executable code.

### P0-4 — Dead retry, wrong quota
The `try/except` that shadowed the retry decorator is gone; error handling lives only in
`_execute_with_retry`. It retries 429/500/502/503/504, never 4xx client errors, prefers the
server's structured `RetryInfo.retryDelay`, and falls back to jittered exponential backoff
capped at 32s. A circuit breaker opens after 5 consecutive failures. Limits come from
`config/limits.yaml`.

### P0-5 (new) — `supporting_image_ids` was off by one
Ground truth uses `img_1`, `img_2`. The code emitted `img_0`-based ids from
`f"img_{idx}"`. **Every populated `supporting_image_ids` cell was wrong against the
grader.** Centralised in `contract.image_id()`.

### P0-6 (new) — `risk_flags` were out of vocabulary
`user_risk.py` emitted `high_rejection_rate`, `frequent_manual_reviews`, `suspicious_history`
— none of which appear in the grader's 10-value set. Specifics now live in `detail_flags`
(audit only); the CSV gets `user_history_risk`.

### P1-1 — Fabricated evaluation report
The hardcoded "Operational & Cost Analysis" and "High-Load Production Strategies" sections
are deleted rather than corrected. The report now carries only measured classification
metrics, plus a **coverage** figure — the old evaluator would report 100% on a single
matching row. Join key fixed from the non-unique `user_id + claim_object` to
`user_id + image_paths`.

### P1-2 — Unconstrained schemas
Zero `Literal` types existed; vocabulary was advisory prose. Now enforced through
`response_schema`. The old `minor/moderate/severe` severity words are gone — the grader
scores `none/low/medium/unknown`.

### P1-4 — Prompt injection
Claim text is wrapped by `wrap_untrusted()` in a delimited block labelled as data, with
forged delimiters stripped. `detect_injection()` runs deterministically regardless of what
the model concluded, so a prompt that successfully steers the model still raises
`text_instruction_present`.

---

## 3. Verification

### Test suite

```
$ ./venv/bin/python -m pytest
74 passed in 0.44s
```

No live API calls; the suite is hermetic and runs in under half a second.

### CLI (P0-1 fixed, images genuinely absent)

```
$ ./venv/bin/python -m agent_core.main --limit 3 --skip-validation-run

  WARNING: no 'images/' directory under /Users/.../HackerRank Hackathon.
  Text-only inference is DISABLED, so these claims will resolve to not_enough_information.

[batch 1/3] user_002 (car)...
[Decision] Short-circuit: no usable image evidence, skipping LLM pipeline.
    -> not_enough_information / severity=unknown
[batch 2/3] user_005 (car)... -> not_enough_information / severity=unknown
[batch 3/3] user_004 (car)... -> not_enough_information / severity=unknown
batch: 3 rows written, 0 hard failures, 0.0s total
```

Rows are written, the missing evidence is stated plainly, and **zero LLM calls were spent**
discovering that there was nothing to look at.

### Live adversarial run — the part that matters

Seven crafted claims against four real photographs (`tests/fixtures/`). The `car_damage.jpg`
image shows a grey car with a gouge and dent on the **front bumper** — real damage, but
nothing like a destroyed bumper.

| Case | Expected | Got | |
|---|---|---|---|
| adv_001 truthful front-bumper claim | supported | **supported** | PASS |
| adv_002 "completely destroyed, needs full replacement" | contradicted | **contradicted** | PASS |
| adv_003 cat photo for a car claim | contradicted | not_enough_information | **FAIL** |
| adv_004 claims *rear* bumper, photo shows *front* | not_enough_information | **not_enough_information** | PASS |
| adv_005 blank image | not_enough_information | not_enough_information | (quota died) |
| adv_006 blurred image | not_enough_information | not_enough_information | (quota died) |
| adv_007 injection attempt | supported | — | **untested** |

**adv_002 and adv_004 are the two cases the whole system exists for, and both are correct.**

adv_002 caught severity inflation from a real photograph:
> "The claimant asserted that the car's front bumper was 'completely destroyed and broken
> off'... However, the Vision analysis (img_1) clearly shows the front bumper with
> significant damage, including a dent..."

adv_004 is the distinction the spec calls out explicitly — claimed part not visible must be
`not_enough_information`, never `contradicted`:
> "the Vision analysis (img_1) explicitly states that 'The claimed part, the rear bumper, is
> not visible in the provided image.'"

The old pipeline could not reach either result: it had no images, no `claimed_part_visible`
signal, and a severity vocabulary the grader does not use.

### The no-fabrication guarantee, under real failure

Claims 5-7 hit quota exhaustion mid-run. Every one returned
`not_enough_information`, confidence 0, `manual_review_required=True`, with the real 429 in
`escalation_reason`. **Zero fabricated verdicts.** Under the previous code these three
would have been confident `supported` approvals — that is precisely what the Phase 0 trace
recorded six times.

The circuit breaker also did its job: after 5 consecutive failures it opened, and adv_007
failed in **0.0s** rather than burning 16 more doomed calls.

---

## 4. What I could not verify

- **adv_007 (prompt injection) never ran.** Quota was exhausted before it executed. The
  unit tests cover `detect_injection` and delimiter forging, but the end-to-end behaviour
  — model steered, flag still raised — is unproven against the live API.
- **adv_005 / adv_006 results are not evidence of correctness.** They returned the expected
  verdict, but via the error path, not via analysis. I have counted them as untested.
- **No accuracy baseline on `sample_claims.csv`.** Still blocked: those 20 claims reference
  `images/sample/`, which does not exist. This remains open question #1 from the audit.
- **The fan-out is still sequential.** Unchanged in this phase; it is Phase 2 work.
- **`platform_backend` was edited but not exercised.** No server was started. The state-key
  and routing fixes there are reasoned, not tested.
- **`submission_package/` still exists.** I copied its four test images to `tests/fixtures/`
  but did not delete the fork — that is a destructive change I would rather do deliberately.

---

## 5. The finding that changes the plan

The Phase 0 audit measured a **5 RPM** ceiling. This run surfaced the harder one:

```
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: 20
```

**Twenty requests per day.** At 4 LLM calls per claim, the free tier processes **five claims
per day**. The 44-claim batch is not slow on free tier — it is impossible. Even after Phase
2 collapses 4 calls into 1, the ceiling is 20 claims/day, still under the batch size.

`config/limits.yaml` now records `rpd: 20`, and the governor refuses immediately rather than
blocking on a 24-hour window (a wait that would look like a hang).

This makes the Phase 2 exit criterion — "zero 429s across a full 44-claim batch" —
unachievable on free tier by arithmetic, not by engineering. **Phase 2 needs a paid key, or
that criterion needs rewriting.** This is audit open question #3 and it is now blocking
rather than advisory.

---

## 6. Known gaps introduced or left open

1. **adv_003: wrong object → `not_enough_information`, should be `contradicted`.** Vision
   correctly reported "No car or car parts are visible"; the decision agent weighted
   "claimed part not visible" over "wrong object photographed". The fix is the deterministic
   alignment engine with an explicit `object_match` signal — Phase 4.3/4.4 — not more prompt
   text. Logged, not patched.
2. **RPD tracking is process-local and resets on restart.** Two processes each believe they
   own 20 requests. Needs the Redis-backed budget from Phase 2.2.
3. **The client is still synchronous.** Correct now, not fast. Phase 2.1.
4. **Cache is still per-agent**, so a warm claim is 4 lookups rather than 1. Phase 2.4.
5. **`evaluate.py` reports no latency or cost**, deliberately — it does not observe the
   pipeline. `PERFORMANCE.md` is a Phase 2 deliverable.

---

## 7. Recommended next step

Proceed to **Phase 1 (target architecture, design doc, no code)** as originally scoped. The
repo now runs, fails honestly, and has a regression suite holding the contract in place, so
Phase 1 can be designed against observed behaviour instead of a stale CSV.

Two things I need from you before Phase 2 becomes executable:

1. **Rotate `GEMINI_API_KEY`** — see `docs/SECRET_ROTATION.md`. Free tier is exhausted for
   today regardless.
2. **Decide on tier.** Free tier caps the system at 5 claims/day. If the 44-claim batch must
   run, that requires billing enabled. If it must not, tell me and I will rewrite the Phase 2
   exit criteria around a realistic budget.

And still open from the audit: **where are the claim images?** Everything in Phases 3-4
depends on them, and the adversarial fixtures I built are a stopgap of 4 photographs, not a
dataset.
