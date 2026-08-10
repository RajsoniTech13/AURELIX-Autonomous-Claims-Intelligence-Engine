# AURELIX — Phase 0 Audit

**Date:** 2026-08-08
**Commit audited:** `ff084a1` (branch `main`, working tree clean)
**Scope:** `agent_core/`, `platform_backend/`, `frontend/`, `submission_package/`, `scripts/`
**Code changes made:** none. This document is observation only.

---

## Executive summary

Five things matter more than everything else in this document:

1. **The CLI produces zero output rows.** `agent_core/main.py` reads four state keys the graph never
   writes. Every claim raises `KeyError`, is swallowed by a bare `except`, and is skipped.
   `output.csv` on disk is a stale artifact from an older, deleted pipeline.
2. **There is no vision.** The image files referenced by every row of `claims.csv` do not exist in the
   repository. The vision agent therefore always runs in text-only mode and invents damage findings
   from the claim narrative. Every "photo shows a scratch on the rear bumper" in `output.csv` was
   produced without a photo.
3. **The system fabricates verdicts on API failure.** On any exception the Gemini client returns a
   hardcoded `"claim_status": "supported", "confidence": 85`. I observed this fire 6 times in a
   3-claim trace. One claim had 4/4 LLM calls fail and still emitted a confident "supported" verdict.
   This is the ground-rule-7 violation, and it is live.
4. **The retry logic is dead code.** A `try/except` inside the function catches the error before the
   `@retry_on_api_error` decorator can see it. Zero retries ever execute.
5. **The reported 100% F1 is not a valid measurement** and cannot be reproduced.

*(An earlier revision of this document also claimed the fan-out does not run concurrently.
That was wrong — see the correction in §2.3. The fan-out is genuinely concurrent; the
latency comes from a serial chain of four LLM round trips.)*

---

## 1. File inventory

### 1.1 `agent_core/` — the reasoning library (2,243 LOC)

| File | LOC | Real responsibility | Status |
|---|---:|---|---|
| `orchestrator/graph.py` | 452 | LangGraph `StateGraph`, 9 nodes, fan-out topology | **Live.** Fan-out does not actually run concurrently (§2.3) |
| `main.py` | 233 | CLI batch runner + CSV I/O + evaluation trigger | **Broken.** Reads nonexistent state keys (P0-1) |
| `services/gemini_client.py` | 320 | Gemini SDK wrapper, cache, rate limiter, retry, mock fallback | **Live, and the source of P0-2/P0-3/P0-4** |
| `schemas/models.py` | 185 | Pydantic v2 agent I/O contracts | **Live.** Zero `Literal[]` constraints — every field is unconstrained `str` (P1-2) |
| `evaluation/evaluate.py` | 192 | Accuracy report generator | **Live but partly fabricated.** §2 and §3 of its output are hardcoded prose (P1-1) |
| `prompts/templates.py` | 151 | 4 prompt templates | **Live.** Claim text interpolated directly into prompt (P1-4) |
| `agents/user_risk.py` | 125 | Deterministic risk scoring from history CSV | Live, sound |
| `agents/policy_verification.py` | 111 | Deterministic evidence-rule check | Live, sound |
| `services/vector_store.py` | 113 | Hand-rolled TF-IDF + cosine | Live. Rebuilt per process, not per claim (§3, P2-1) |
| `agents/vision_analysis.py` | 76 | Vision or text-mode damage detection | **Live but always text-mode** (P0-2) |
| `agents/image_validator.py` | 74 | Format/resolution pre-flight | Live. Returns `valid=True` for paths that don't exist (P0-2) |
| `agents/similar_claims.py` | 68 | TF-IDF retrieval wrapper | Live |
| `agents/decision.py` | 53 | Final LLM verdict | Live |
| `agents/fraud_review.py` | 48 | LLM fraud reasoning | Live |
| `agents/claim_ingestion.py` | 33 | LLM claim parsing | Live |
| `agents/__init__.py` and 5 other `__init__.py` | 6 | — | Empty |

### 1.2 `platform_backend/` — FastAPI gateway (782 LOC)

| File | LOC | Responsibility | Status |
|---|---:|---|---|
| `api/routes.py` | 305 | 8 endpoints, incl. SSE stream | Live. Synchronous, unversioned, unauthenticated |
| `services/claim_service.py` | 175 | Graph invocation + SSE event generation | Live. Emits fake "running" events (P2-4) |
| `models/schemas.py` | 102 | Pydantic request/response models | Live |
| `db/models.py` | 70 | SQLAlchemy ORM | Live. `create_all`, no Alembic |
| `services/cache.py` | 53 | Redis wrapper | Live |
| `config.py` / `db/session.py` / `main.py` | 72 | Settings, sync engine, app factory | Live. Sync SQLAlchemy throughout |

### 1.3 Dead code and duplication

- **`submission_package/` (2,289 LOC, 40 files tracked in git) is a complete stale fork of
  `agent_core`.** It implements a *different* 10-node pipeline with agents that no longer exist in
  the live tree (`claim_understanding`, `image_quality`, `evidence_compliance`, `confidence`,
  `fraud_intelligence`, `human_review`), and a different LLM layer (`llm.py` + `vision_llm.py`
  instead of the unified `gemini_client.py`). **This fork is the pipeline that actually produced the
  `output.csv` and the 100% evaluation report currently on disk.** Nothing imports it. Delete it.
- `test_graph.py`, `test_db_hang.py` (root) — ad-hoc scratch scripts, not tests. `test_db_hang.py` is
  3 lines and does nothing. `test_graph.py` sets `MOCK_LLM=true`, which no code reads.
- `agent_core/schemas/models.py:151-185` — `class ClaimsState: pass`, a docstring-only stub. The real
  TypedDict lives in `graph.py`. Two sources of truth for the state contract.
- `agent_core/schemas/models.py:139` — `BranchFailureOutput` is defined, documented in the graph
  docstring, and **never instantiated**. The graph builds raw dicts instead.
- `aurelix_agent_core.zip` (406 KB), `log.txt` (81 KB), `aurelix.db` (90 KB) — untracked build/run
  detritus in the repo root. Correctly gitignored, but should be removed from the working tree.
- `MOCK_LLM` — referenced in a comment at `gemini_client.py:28` and set by `test_graph.py`. **No code
  reads it.** Dead configuration that reads as a working feature.
- `venv/` (Python 3.14) is untracked. Good.

### 1.4 The three READMEs disagree. None is correct.

| Source | Claim | Reality |
|---|---|---|
| `README.md:89` | "parallel **7-agent** validation graph" | 9 `add_node` calls |
| `submission_package/README.md:93` | "**10-node** State Machine" | True *for the dead fork only* |
| `agent_core/ARCHITECTURE_DETAILS.md` | no count given | — |
| `agent_core/output/evaluation_report.md:157` | "396 node runs (**9 agents** × 44 claims)" | 9 nodes, but only 44×0 rows were produced |

**Ground truth from code:** `agent_core/orchestrator/graph.py` registers **9 nodes**, of which
**7 are agents** (image_validator is a non-LLM utility, short_circuit_decision is an error path).
Of the 7 agents, **4 call Gemini** (ingestion, vision, fraud, decision) and **3 are deterministic**
(policy, similar_claims, user_risk). The root README's "7 agents" is right by accident and wrong in
substance — it calls the graph "parallel", which it is not.

Other stale claims: `README.md:119` documents `docker run ... aurelix-backend`. **There is no
Dockerfile anywhere in the repo.** There is no `docker-compose.yml` and no `.github/` CI.

---

## 2. Execution trace

Instrumented harness: wrapped every `node_*` function in `graph.py` and the raw
`client.models.generate_content` call to capture wall-clock, token counts, retries, and rate-limiter
sleep. Ran the **first 3 rows of `agent_core/data/claims.csv`** against the live Gemini API.

### 2.1 Latency waterfall (measured, ms)

```
TF-IDF index build (once per process): 3 ms

claim node                       wall_ms  llm   tok_in  tok_out  err
================================================================================
1     image_validator                  0    0        0        0    0
1     claim_ingestion               5878    1      240      104    0
1     policy_verification              0    0        0        0    0
1     user_risk                        0    0        0        0    0
1     similar_claims                  31    0        0        0    0
1     vision_analysis               9034    1      366      307    0
1     fraud_review                  5462    1      849      132    0
1     decision                      6881    1     1053      275    0
      -- TOTAL --                  27265    4     2508      818    0
         rate-limiter sleep:            0 ms
--------------------------------------------------------------------------------
2     claim_ingestion               2739    1      216      102    0
2     vision_analysis               5996    1      310      182    0
2     fraud_review                   203    1        0        0    1   <- 429, faked
2     decision                      4018    1        0        0    1   <- 429, faked
      -- TOTAL --                  12963    4      526      284    2
         rate-limiter sleep:         5066 ms
--------------------------------------------------------------------------------
3     claim_ingestion               3986    1        0        0    1   <- 429, faked
3     vision_analysis               3997    1        0        0    1   <- 429, faked
3     fraud_review                  4009    1        0        0    1   <- 429, faked
3     decision                      3985    1        0        0    1   <- 429, faked
      -- TOTAL --                  15986    4        0        0    4   <- 100% FABRICATED
         rate-limiter sleep:        15200 ms
================================================================================
```

### 2.2 What this shows

- **Clean-path latency is 27.3 s** for one claim (claim 1, all 4 calls served). The Phase 2 target is
  ≤ 8 s p95. We are **3.4× over budget** on the single best-case observation.
- **Claim 3 is the nightmare case.** All four LLM calls returned 429. The pipeline emitted a
  complete, confident verdict anyway — `status: success`, `confidence: 85`, `claim_status: supported`
  — assembled entirely from `_get_mock_response()`. No error surfaced to the caller. An operator
  reading the output cannot distinguish this from a real decision.
- **The rate limiter makes things worse, not better.** On claim 3 it slept 15.2 s of the 16.0 s total
  and *still* got throttled on every call, because it is configured for the wrong limit (§3, P0-4).
- **Retries: zero observed.** Every 429 resolved in ~200 ms with a single attempt. The API returned
  `RetryInfo { retryDelay: "47s" }` and it was discarded.

### 2.3 The latency is a serial chain of LLM calls

> **CORRECTED 2026-08-08.** This section originally claimed the fan-out does not run
> concurrently. **That was wrong**, and the reasoning behind it was invalid. Corrected below;
> the original inference is preserved so the error is auditable.
>
> *Original claim:* for claim 1 the node latencies sum to `5878 + 31 + 9034 + 5462 + 6881 =
> 27,286 ms` against a measured end-to-end of `27,265 ms` — agreement to 0.1%, therefore no
> overlap.
>
> *Why that does not follow:* of the four "parallel" branches, only `vision_analysis` does
> meaningful work (9,034 ms). `policy_verification` and `user_risk` are 0 ms and
> `similar_claims` is 31 ms — all deterministic Python. So the parallel section's wall time is
> `max(9034, 31, 0, 0) ≈ 9034` either way. Sum ≈ total is equally consistent with perfect
> concurrency. I mistook a degenerate case for evidence.

Measured directly against the installed LangGraph (1.2.6), four branches each sleeping 1.0 s:

| Execution mode | Wall clock |
|---|---:|
| sync nodes + `.invoke()` | **1.01 s** |
| sync nodes + `.ainvoke()` | **1.00 s** |
| async nodes + `.ainvoke()` | **1.00 s** |

Concurrent, in every mode. Sync node functions are dispatched to a thread pool, so a
blocking node does not stall its siblings.

**The real latency structure** is the serial chain, not the fan-out:

```
ingest → vision → fraud → decision
5.9s      9.0s     5.5s     6.9s      = 27.3s of strictly sequential LLM round trips
```

The fan-out contributes nothing to the critical path because three of its four branches are
free. The fix is therefore **fewer sequential round trips** (collapse ingest+vision into one
multimodal call; keep fraud/decision deterministic), not "make the fan-out parallel" — it
already is.

A second, separate serialiser existed in the old client: `APIRateLimiter.wait()` held a
`threading.Lock` *across* its `time.sleep()`, so every concurrent branch queued behind one
mutex. That is fixed in Phase 0.5 — the replacement governor sleeps outside the lock.

Also confirmed: LangGraph raises `InvalidUpdateError` when two concurrent nodes write the
same state key without a reducer, so disjoint state slices are enforced by the framework
rather than by convention.

---

## 3. Bug ledger

### P0 — blocks correct operation

**P0-1 · CLI writes an empty CSV; every claim is silently dropped**
`agent_core/main.py:92-96` reads `state_res["quality"]`, `["compliance"]`, `["escalation"]`.
The graph's `ClaimsState` (`graph.py:60-82`) defines no such keys — the equivalents are named
`image_validation`, `policy`, and (absent). Each claim raises `KeyError: 'quality'`, caught by the
bare `except Exception` at `main.py:84`, which prints and `continue`s. The identical bug is repeated
in the validation loop at `main.py:174`.
*Reproduction:*
```
state = process_claim(user_id="user_002", image_paths="a.jpg", user_claim="...", claim_object="car")
sorted(state)  # -> [... 'decision','fraud','image_validation','ingestion','policy','similar_claims','user_risk','vision']
state["quality"]  # KeyError
```
*Root cause:* `main.py` was carried over verbatim from the `submission_package` 10-node pipeline when
`graph.py` was rewritten to 9 nodes with different names. The output contract was never re-wired.
*Consequence:* `output.csv` in the repo is a **stale artifact of the deleted fork**, not a product of
the current code. Any claim that the current system scores 100% is unsupported.

**P0-2 · The vision pipeline has never seen an image**
`agent_core/data/claims.csv` references `images/test/case_001/img_1.jpg` and 43 similar paths.
`find . -type d -name images` returns nothing — **the directory does not exist**, in the working tree
or in git. `sample_claims.csv` likewise references a nonexistent `images/sample/`.
The failure is silent by design: `image_validator.py:32-40` sees `images=None` but a non-empty path
string and returns `valid=True, file_count=len(paths)` — a "text-mode fallback". Downstream,
`vision_analysis.py:50` takes the `else` branch and calls `call_gemini_text` with
`VISION_ANALYSIS_PROMPT`, which asks the model to determine severity and impact direction from
*file paths and claim text*.
*Consequence:* every `object_part`, `issue_type`, `severity`, and `supporting_image_ids` value in
`output.csv` is a hallucination. This is visible in the data: row 2's claim is a **dent on the door**;
the recorded output is `issue_type=scratch, object_part=rear_bumper`, justified as "The image shows
only minor scratch on the door" — describing an image that does not exist, about a part it did not
name. The canonical hard case from the spec (§1) is unreachable: it requires comparing a claimed part
against an observed part, and nothing is ever observed.

**P0-3 · Silent fabrication of verdicts on any LLM failure**
`gemini_client.py:249-251` and `312-314`:
```python
except Exception as e:
    logger.error(f"[Gemini] API completely failed after retries: {e}. Falling back to mock data.")
    return _get_mock_response(response_model)
```
`_get_mock_response` (`:187-200`) returns a hardcoded `DecisionOutput` with
`claim_status="supported", confidence=85, justification="Mock mode: Claim approved automatically."`
The `except` is unconditional — it catches 429s, timeouts, auth failures, schema-validation failures,
and genuine bugs alike, and converts all of them into an approved claim.
*Observed 6 times in a 3-claim trace* (§2.1). Claim 3 produced a fully synthetic verdict.
*Root cause:* a demo-stability hack (the docstring at `:139-141` says "Reduced attempts to 2 to fail
fast and trigger mock fallback for demos") that was never removed. Directly violates ground rule 7.

**P0-4 · Rate limiter is configured for 3× the actual quota, and retry is dead code**
Two compounding defects in `gemini_client.py`:
- `:63` — `APIRateLimiter(rpm=15)`, with the comment "Google Gemini Free Tier allows 15 RPM". The API
  disagrees. Measured response: `quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier,
  quotaValue: '5', model: gemini-2.5-flash`. **The limiter admits 3× more traffic than the quota
  allows**, guaranteeing 429s, which then trigger P0-3.
- `:134-163` — `@retry_on_api_error` wraps `call_gemini_text`/`call_gemini_vision`, but the
  `try/except Exception` *inside* those functions (`:249`, `:312`) swallows the exception before it
  can propagate to the decorator's `wrapper`. **The retry loop can never execute.** Confirmed by
  trace: every 429 resolved in ~200 ms with one attempt and no backoff sleep.
- The API returns a structured `RetryInfo { retryDelay: "47s" }`. The code instead regex-matches
  `r"retry in (\d+\.?\d*)s"` (`:153`) against the stringified exception — a pattern that does not
  appear in the actual error text (which reads `Please retry in 47.259966199s`, so it happens to
  match, but only by luck and only in English). No jitter, no cap, no circuit breaker.

### P1 — correctness and security

**P1-1 · The evaluation report is partly fabricated, and its headline metric is invalid**
`evaluation/evaluate.py:153-187` writes §2 "Operational & Cost Analysis" and §3 "High-Load Production
Strategies" as **hardcoded string literals**, not measurements. The report on disk therefore asserts,
falsely: model `gpt-4o-mini` (the project uses Gemini); "~2.4 seconds per claim (Live LLM mode)"
(measured: 27.3 s); "token bucket limiting … 200 RPM" (no token bucket exists; the limiter is a
single mutex-guarded sleep); "retries up to 3 times before … escalating to `human_review` with the
reason 'AI Node Timeout Exception'" (no retry executes, and there is no `human_review` node in the
live graph). For an insurance product these numbers are audit-trail claims, and they are wrong.

The measured §1 is also not trustworthy. It reports **100% accuracy / 100% macro-F1 on all 20 sample
claims**. I verified the predictions are not a literal copy of ground truth (0/20 justifications
match). But the score is unreproducible and structurally implausible:
- It was produced by the **deleted `submission_package` fork**, not the current code.
- Every non-`supported` ground-truth label turns on what the photograph shows —
  *"The submitted image shows another part of the car"* (claim_006), *"the screen is not shattered;
  only a minor scratch is visible"* (claim_013), *"The image shows only minor box creasing"*
  (claim_019). The claim text asserts the opposite in each case. **A text-only system has no
  information channel that can recover these labels**, yet it scored 7/7 on them.
- The evaluator joins on `f"{user_id}_{claim_object}"`, which is not unique across the corpus, and
  silently scores only keys present in both files — a run that emits 1 row out of 20 would still
  report 100%.

Treat the existing baseline as **unmeasured**. Establishing a real one requires P0-1 and P0-2 fixed
first.

**P1-2 · No enum constraints anywhere in the "structured output" schemas**
`grep -c "Literal\[" agent_core/schemas/models.py` → **0**. Every controlled-vocabulary field
(`severity`, `issue_type`, `claim_status`, `risk_level`, `impact_direction`) is a bare `str` with the
vocabulary described only in the `Field(description=...)` — advisory text the model may ignore.
Concretely: `VisionAnalysisOutput.severity` documents `none|minor|moderate|severe`, but ground truth
uses `low|medium|unknown|none` and `output.csv` contains `low`. **The declared vocabulary and the
scored vocabulary do not intersect on 3 of 4 values.** `response_schema` is correctly wired into
`GenerateContentConfig` (`:230-234`) — the mechanism is right, the schema is just empty of
constraints, so it buys nothing beyond JSON-shape.

**P1-3 · Committed API key prefix** — *severity downgraded, see note*
`agent_core/README.md:54` contains `GEMINI_API_KEY=AQ.Ab8RN...`. Present in **2 commits**
(`ff084a1`, `e4ce2159`), and it is a genuine prefix of the then-live key (8 of 53 characters).

> **CORRECTED 2026-08-08.** I originally described this as leaking key material. After the key
> was rotated, the *replacement* key is also 53 characters and also begins `AQ.Ab8RN` —
> confirming this is a **structural prefix common to all Gemini keys of this generation**, not
> a secret-bearing fragment. Leaking it is closer to leaking `sk-` from an OpenAI key.
> **Real severity: low, not moderate.** Rotation was still correct and has been done; the
> history purge in `docs/SECRET_ROTATION.md` is now optional hygiene rather than remediation.
`.env` itself is **not tracked** and `.gitignore` already covers `.env`, `.env.local`, `.env*.local`
(lines 34-38) — so the gitignore work is already done. **Rotate the key regardless**, then purge the
README line from history. No other secrets found: a scan of all 4 commits for `AIza*`, `sk-*`, and
`AQ.Ab8RN*` patterns returns only this one file.

**P1-4 · Prompt-injection surface**
`prompts/templates.py` interpolates raw claim text directly into the instruction body via `.format()`
— `CLAIM_INGESTION_PROMPT:38`, `VISION_ANALYSIS_PROMPT:61`, `FRAUD_REVIEW_PROMPT:116`. There is no
delimiter, no "treat as data" instruction, and no detection. `FRAUD_REVIEW_PROMPT:103` lists
`text_injection` as a fraud indicator the *model* should notice, which is not a control.
This is a live gap against the benchmark: `claim_020`'s own ground-truth justification reads
*"Any instruction-like text inside the image should be ignored"* — the sample set contains an
injection case and the system has no handling for it.
Secondary: `.format()` on attacker-influenced templates will also raise on stray `{}` in claim text.

**P1-5 · 19 broad `except Exception` handlers, several load-bearing**
Worst offenders: `main.py:84,174` (hides P0-1 — the reason this bug survived); `gemini_client.py:249,312`
(is P0-3); `graph.py:186,220,248,275` (converts branch failures into `{"status":"failed"}` dicts that
the prompt then instructs the model to treat as "unknown", so a crashed branch degrades a verdict
instead of blocking it). `routes.py:110` is a truly bare `except Exception:` with no logging.

### P2 — performance and hygiene

**P2-1 · TF-IDF index rebuilt per process, vocabulary is unbounded**
`vector_store.py:19-53`. Measured build: 3 ms for 20 docs — not currently a bottleneck, and it is
built once at `main.py:50`, not per claim. But `search()` (`:66-67`) iterates the **entire vocabulary**
on every query to apply IDF, making each search `O(|V|)` rather than `O(|query|)`; and the dense
`np.zeros(len(vocab))` vectors are `O(n·|V|)` memory. It will not survive a real corpus.
Also: retrieval has **no metadata filter** — a laptop claim can and does retrieve car claims.

**P2-2 · Per-claim work duplicated across the CLI**
`main.py` runs the full pipeline twice over overlapping data (44 claims at `:63`, then 20 sample
claims at `:155`) with a ~120-line copy-pasted mapping block (`:98-127` ≡ `:186-215`). Sequential
loop, no concurrency, no checkpoint, no progress bar, no per-claim timeout. A crash at claim 40 loses
all 40.

**P2-3 · Cache is keyed per-agent, not per-claim, and is process-local by default**
`compute_cache_key` (`:69-81`) includes `agent_name`, so a single claim occupies 4 cache entries and
a warm re-run still executes 4 round trips of cache lookups plus any misses. `hash_image_bytes`
(`:84-91`) hashes only `img.tobytes()[:4096]` — the first ~4 KB of raw pixels, i.e. the **top few
scanlines**. Two photos with an identical sky will collide. Redis is opened and closed on *every*
get and set (`:101-103`, `:121-123`) — a new connection per cache operation.

**P2-4 · SSE stream emits fabricated progress events**
`claim_service.py:136-139` yields `"running"` events for `vision_analysis`, `policy_verification`,
`similar_claims`, and `user_risk` **all at once, unconditionally**, before knowing whether any of them
started. The UI's "agents working in real time" timeline is theatre, not telemetry.

**P2-5 · Web layer is unhardened**
No auth of any kind. No `/v1` prefix. No rate limiting. No idempotency. No pagination cursor.
Sync SQLAlchemy `create_engine` + `Base.metadata.create_all` (`db/session.py:10,15`) — no Alembic, so
no migration path. Upload handling (`routes.py:174-186`) trusts `PIL.Image.verify()` with no size cap
and no content-type sniffing, and calls `await f.read()` twice on the same `UploadFile`. No
`/health`, `/ready`, or `/metrics`. No structured logging, no `trace_id`, no OpenTelemetry.

**P2-6 · Repo hygiene**
`submission_package/` (40 tracked files, 2,289 LOC) is a tracked dead fork — see §1.3. No Dockerfile
despite `README.md:119` documenting `docker run`. No `docker-compose.yml`. No `.github/` CI. No
`.env.example`. No `pytest` (not even installed); the three `test_*.py` files are scratch scripts.
The only hardcoded absolute path is in generated output (`evaluation_report.md:9`), not in code.

---

## 4. Accuracy baseline

**I could not produce one, and I want to be explicit about why rather than report a number I don't
trust.**

Three independent blockers:

1. **P0-1** — the current CLI emits zero rows, so there is nothing to score.
2. **P0-2** — the images do not exist, so even with P0-1 fixed the vision path cannot be exercised.
   Any score measured now would be a text-only score for a system whose labels require pixels.
3. The project's Gemini quota was exhausted during the §2 trace (`limit: 5 RPM`), so a fresh 20-claim
   run (80 LLM calls) would take ≳16 minutes of pure throttling and would be contaminated by P0-3
   fabrications anyway.

**What exists on disk instead:** `agent_core/output/evaluation_report.md` claims 100% accuracy,
100% macro-F1, and a perfect confusion matrix (supported 13/13, contradicted 4/4, NEI 3/3) over
20 claims. I verified the underlying `validation_output.csv` matches ground truth 20/20 on both
`claim_status` and `severity`, and is not a copy-paste (0/20 justifications identical). **It is
nonetheless invalid as a baseline** — it was generated by the deleted `submission_package` fork, and
it scores 7/7 on labels that are only recoverable from photographs the system never received (P1-1).

**Recommended real baseline, once P0-1 and P0-2 are fixed:** score against `sample_claims.csv`
(n=20; distribution `supported` 13 / `contradicted` 4 / `not_enough_information` 3 — small and
imbalanced, so report per-class CIs and don't over-read macro-F1). The 4 contradicted + 3 NEI cases
are the ones that matter; they are exactly the cases §1 of the spec is about.

**Sourcing the images is a prerequisite for Phase 4 and is currently unresolved** — they are neither
in the repo nor in git history. I need to know whether they exist elsewhere (see §7).

---

## 5. Cost and quota baseline

Measured from the §2 trace, claim 1 (the only claim where all 4 calls were served):

| Metric | Measured |
|---|---:|
| LLM calls per claim | **4** (ingestion, vision, fraud, decision) |
| Input tokens per claim | **2,508** |
| Output tokens per claim | **818** |
| Wall-clock per claim (warm, no throttle) | **27.3 s** |
| Effective quota (this project, `gemini-2.5-flash`) | **5 RPM** (reported by the API) |

Token growth is structural: the fraud prompt embeds ingestion+vision+policy+risk JSON (849 in), and
the decision prompt embeds all five prior outputs (1,053 in). The same system prompt and rulebook are
re-sent on all 4 calls — with context caching that is near-eliminable.

**Cost per claim** (assumption: `gemini-2.5-flash` at $0.30/1M input, $2.50/1M output — **verify
against current pricing before quoting this**):
`2,508 × $0.30/1M + 818 × $2.50/1M` = **≈ $0.0028/claim** → **≈ $0.12 for the 44-claim batch**.
Note the existing report's $0.00048/claim is ~6× low and priced against the wrong model.

**Projection at 10 concurrent users, 1 claim each:**
`10 × 4 = 40 requests`. At the measured **5 RPM** ceiling that is **8 minutes** of serialized quota
for a single burst — before any retry. The current limiter is set to 15 RPM, so it will admit the
burst, collect ~35 × 429, and (via P0-3) return **~35 fabricated "supported" verdicts**.
Even at a paid 1,000-RPM tier, 4 calls/claim caps throughput at 250 claims/min and keeps per-claim
latency at ~27 s, because the bottleneck is the sequential node chain, not the quota.

The Phase 2 targets (≤8 s p95, zero 429s across 44 claims) are unreachable without collapsing 4 calls
to 1, making the fan-out genuinely concurrent, and governing the rate to the real quota.

---

## 6. What I verified vs. did not

**Verified by execution:**
- P0-1 — ran `process_claim` with a stubbed LLM, dumped state keys, reproduced `KeyError: 'quality'`.
- P0-3, P0-4, §2 waterfall, §5 tokens — instrumented live 3-claim run against the real Gemini API.
- P0-2 — `find` over the repo and git history; no `images/` directory exists.
- P1-1 — re-scored `validation_output.csv` against `sample_claims.csv` (20/20 status, 0/20 identical
  justifications); read the hardcoded report literals in `evaluate.py:153-187`.
- P1-2 — `grep -c "Literal\["` → 0.
- P1-3 — `git grep` across all 4 commits; compared the leaked prefix against `.env` programmatically
  (8/53 chars, prefix confirmed). The key value itself was never printed.
- §1 LOC, node counts, README claims, absence of Dockerfile/compose/CI — direct file inspection.

**Not verified:**
- **Accuracy of any kind** — blocked, see §4.
- **The `frontend/`** — I did not run it or read its components (612 MB `node_modules`, outside the
  Phase 0 critical path). Its correctness is unassessed.
- **Concurrency behaviour under real load** — the §2.3 sequentiality finding is from single-claim
  timing arithmetic, not a load test.
- **Current Gemini pricing** — §5 dollar figures rest on a stated assumption I did not check against
  live pricing.
- **`platform_backend` endpoints end-to-end** — read but not exercised; no server was started.

---

## 7. Open questions for you

1. **Where are the claim images?** `images/test/` and `images/sample/` are referenced by all 64 rows
   of input data and exist nowhere in the repo or its history. Without them, Phases 3-4 (vision,
   pHash fraud detection, the canonical front-bumper case) cannot be built or validated. Do you have
   them, or do we need to source/synthesise a set?
2. **Rotate `GEMINI_API_KEY` now.** The prefix is committed and the quota is currently exhausted. I
   can prepare the history purge (`git filter-repo`) and `.env.example` in Phase 1, but the rotation
   itself is yours to do in Google AI Studio.
3. **Free tier or paid?** The measured 5 RPM ceiling makes the Phase 2 exit criteria
   (zero 429s across a 44-claim batch) essentially unachievable on free tier even with a perfect
   governor. Confirm which tier we are targeting so the YAML limits are honest.
4. **Confirm the frozen output contract.** I will pin the 14 columns of `output.csv` in a golden test.
   The value vocabulary needs a decision: ground truth uses `low|medium|unknown|none` for severity
   while the schema documents `none|minor|moderate|severe`, and the spec in §1 of the brief proposes
   a third vocabulary (`none|minor|moderate|severe|total_loss`). **These three cannot all be right.**
   My assumption unless told otherwise: `sample_claims.csv` wins, because it is what gets scored.

---

## 8. Recommended next step

Proceed to **Phase 1 (design doc, no code)**. But I'd flag one sequencing concern: P0-1 through P0-4
are four small, well-understood, independently testable fixes that currently make the repo
non-functional and actively misleading. There is a case for landing them as a short Phase 0.5 —
roughly: delete the mock fallback, correct the state-key mapping, set the limiter to the real quota,
and make failure surface as `not_enough_information` + `error_reason` — so that Phase 1 is designed
against a system that runs and reports honestly, rather than one whose only observable output is a
stale CSV from a deleted fork.

Your call. Say the word and I'll do Phase 1 as written, or Phase 0.5 first.
