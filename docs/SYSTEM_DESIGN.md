# AURELIX — System Design

Documents the architecture **as implemented**, verified against the source on 2026-08-10.
Where a component exists but is not wired into the request path, that is stated rather than
implied. Legacy directories are listed in §15 so they are not mistaken for the design.

---

## 1. What the system does

A claimant submits free text plus photographs. AURELIX returns one of three verdicts —
`supported`, `contradicted`, `not_enough_information` — with a confidence score, a fraud
score, a named rule id, and a per-agent audit trail.

The governing constraint is the **Gemini free tier: 20 requests per day per model per
project, 5 per minute**, resetting at midnight Pacific. That is an architectural input, not
a budget preference, and it explains most of the design below.

| Property | Value | Source |
|---|---|---|
| Accuracy | 93.2%, macro-F1 93.2% | `evaluate_synthetic` over 44 synthetic cases |
| Model requests per claim | 1 (web), 1 per 3 claims (batch) | `agent_core/service.py`, `batch_scheduler.py` |
| Pipeline stages | 7, of which **1** touches the network | `PIPELINE_STAGES` |
| Tests | 254, hermetic | `pytest` |
| Output contract | 14 columns, frozen, golden-file tested | `schemas/contract.py` |

---

## 2. Overall architecture and data flow

Three deployable units and one shared reasoning library.

```
Browser (Next.js 16 / React 19, Vercel)
    │  multipart POST + SSE
    ▼
FastAPI gateway (platform_backend, Render)
    │  in-process function call — not a network hop
    ▼
agent_core  ── the reasoning library, shared by the web API and the CSV CLI
    │
    ├─ 1 multimodal request ──► Gemini (google-genai)
    └─ deterministic Python ──► verdict
```

`agent_core` is imported, not served. The web platform and the offline batch runner are two
front doors onto the same `analyse_claim_events()` generator, which is deliberate: a second
inference path would drift from the one the benchmark measures.

**Request flow for a single web claim:**

1. `POST /claims/submit-multimodal-stream` — multipart form, `text/event-stream` response.
2. `services/uploads.read_uploads()` caps, decodes, sniffes and persists each image.
3. CSV lookups for user history and evidence rules (`load_lookups_if_empty`).
4. `generate_claim_stream()` spawns a worker thread running `analyse_claim_events()`, and
   drains a `queue.Queue`, emitting one SSE frame per stage and a `: keepalive` comment
   every 15s of silence.
5. On `done`: map the analysis to a `Claim` row + 7 `AuditLog` rows, commit, emit the full
   claim JSON as the terminal SSE frame.

---

## 3. The seven-stage pipeline

`agent_core/service.py` — `PIPELINE_STAGES` is exported so the API and UI cannot invent
their own list and drift. `LLM_STAGES = {"perception"}`.

| # | Stage | LLM? | Responsibility |
|---|---|---|---|
| 1 | `preflight` | no | Decode, validate format/resolution, measure blur and exposure |
| 2 | `duplicate_check` | no | Perceptual-hash the images against every prior submission |
| 3 | `perception` | **yes** | One multimodal call: what is in the images, what is asserted |
| 4 | `policy_verification` | no | Evidence requirements from CSV, cited by `rule_id` |
| 5 | `user_risk` | no | Claim history, velocity, prior flags |
| 6 | `alignment` | no | Claimed part vs observed part; severity delta |
| 7 | `decision` | no | Fraud score, confidence, first-matching ordered rule |

Two ordering decisions are load-bearing:

- **Preflight gates the model call.** If no image is usable, `perception` is emitted as
  `skipped` and no request is spent. This is the single largest quota saving in the system.
- **The duplicate query runs before the insert.** Querying and inserting cannot be one step
  or every claim would match itself; the index must be seen as it was *before* this claim.
  A detected duplicate does **not** short-circuit perception — the audit trail still needs
  to record what was in the photograph, and `R030` sits below `R010`/`R003` in rule order.

---

## 4. Multi-agent architecture

"Agent" here means a bounded unit with one responsibility and a typed output. Only one is
an LLM call.

### 4.1 `agents/image_validator.py` — preflight (deterministic)
Two supply modes: decoded `PIL.Image` objects (web) or `image_paths` resolved against a base
directory (CSV). Enforces `ACCEPTED_FORMATS`, `MIN_RESOLUTION = (200, 200)`, decodability.
Maps diagnostics onto the frozen `risk_flags` vocabulary. Never raises — callers branch on
`.valid`. Its governing rule: **a declared image path is not evidence.**

### 4.2 `agents/image_quality.py` — quality gate (deterministic, OpenCV)
Blur = variance of the Laplacian; exposure = mean luminance guarded by p05/p95 percentiles.
Bands: `unusable | poor | fair | good`.

`merge_quality()` takes the **worse** of the model's self-report and the measurement — it
never upgrades. The gate sees defocus and underexposure the model rationalises away; the
model sees occlusion, screenshots and wrong subjects the gate cannot. One-way override keeps
both. Thresholds in `config/image_quality.yaml` are derived from the measured Laplacian
distribution of the 49-image evaluation set, and the file carries an explicit warning that
they must be re-derived for real photographs.

### 4.3 `agents/perception.py` — the only LLM call
Batched multimodal request. `build_batch_contents()` interleaves text and images so every
image is structurally adjacent to a label naming its owning claim.

The substantive engineering is **isolation checking**, not batching. `validate_isolation()`
verifies, in order of how badly each would corrupt a verdict:
1. every requested `claim_id` present exactly once,
2. no `claim_id` that was never sent,
3. **no image id outside that claim's own range** — the contamination signature.

Failure raises `BatchIsolationError` and is fatal for the batch. A result that cannot be
vouched for is worse than no result, because a contaminated verdict looks identical to a
good one on the way out.

The response schema (`schemas/perception.py`) deliberately omits alignment fields, fraud
score and verdict. The model reports **observations only**.

### 4.4 `agents/policy_verification.py` — evidence compliance (deterministic)
CSV-driven, never hardcoded. Returns `PASS | WARNING | FAIL` with a reason citing stable
`rule_id`s (`EV-CAR-COUNT`), because "EV-CAR-COUNT failed" is answerable to a claimant and
"the car policy failed" is not.

### 4.5 `agents/user_risk.py` — claimant history (deterministic)
Reads `user_history.csv`. Returns `LOW | MEDIUM | HIGH`. Documented constraint: **user
history never overrides visual evidence** — it only contributes risk context.

### 4.6 `agents/alignment.py` — claimed vs observed (deterministic)
Computes `object_match`, `part_match ∈ {exact, adjacent, mismatch, not_visible, unknown}`,
`severity_delta`, `severity_inflated`.

Both operands come from the model's own report, so asking the model to also do the
subtraction adds a failure mode without adding information.

The **part ontology** is the interesting part: `_SYNONYMS` collapses free text to canonical
names (bonnet→hood, windscreen→windshield, side_panel→quarter_panel) and `_ADJACENT`
encodes parts close enough that damage to one plausibly involves the other (front_bumper ↔
grille/headlight/hood). Without normalisation, "bonnet dented" against an observed "hood
dent" reads as `mismatch` and produces a wrong `contradicted`. Two negative constraints are
encoded as comments: no bare `side` → `package_side` mapping (it swallowed car side
mirrors), and `package_corner` is **not** adjacent to `seal` (different failure modes).

### 4.7 `rules_engine.py` — decision (deterministic)
See §8.

---

## 5. Gemini inference strategy and free-tier optimisation

`agent_core/services/gemini_client.py` (701 lines) is the whole model-facing surface.

**Structured output.** `types.GenerateContentConfig(response_mime_type="application/json",
response_schema=PydanticModel)`. Vocabulary is enforced by `Literal` → schema enum, so the
model cannot return a value outside the frozen contract.

**Batching.** `max_claims_per_request: 3`, `max_images_per_claim: 3`,
`max_images_per_request: 9`. 44 claims → 15 requests instead of 176. Batch size is held at
3 deliberately: quota is not the scarce resource, cross-claim isolation is. The config file
says raising it requires the isolation fixture to still pass.

**Model ladder.** Free quota is per model, so `chain: [gemini-3.6-flash, gemini-3.5-flash,
gemini-2.5-flash]` is 60 requests/day at zero cost. `call_gemini_multimodal()` walks the
ladder, **skipping rungs the persisted ledger already knows are spent** so no request is
burned rediscovering exhaustion. `gemini-2.5-flash-lite` is excluded by comment: measured
404 on this request shape, 13 times.

**Quota ledger** (`services/quota_ledger.py`) persists spend to `.aurelix/quota_state.json`,
keyed by Pacific date. Requests are recorded **before** the call — a request that fails
server-side has still consumed budget, and under-counting is the expensive direction — then
**refunded** on 400/403/404/5xx, because the server never processed them. A missing refund
once silently ate 13 slots.

**Rate governor** (`RateGovernor`) is a per-model sliding-window over RPM, TPM and RPD
simultaneously, not a fixed sleep interval. `acquire()` blocks only when the real budget is
exhausted, and sleeps exactly until the oldest entry ages out. RPD exhaustion **raises
immediately** rather than blocking — waiting 24 hours is not backoff.

**Error taxonomy** — three failure modes with opposite correct responses:

| Condition | Response |
|---|---|
| Per-minute 429 | Retry with server-directed delay |
| Per-day 429 | `DailyQuotaExhausted` — stop, checkpoint, advance ladder |
| 4xx auth/bug | `LLMUnavailableError` — fail fast, never retry |

Scope is read from the structured `QuotaFailure.violations[].quotaId`, not regex over prose.

**Backoff** prefers Gemini's own `RetryInfo.retryDelay` from the parsed error body; otherwise
exponential with full jitter, capped.

**Circuit breaker.** Trips after N consecutive failures, refuses calls for a cooldown, allows
one probe through afterwards. A daily exhaustion is explicitly *not* a breaker failure — the
API is healthy, we are out of budget.

**No mock fallback, anywhere.** `LLMUnavailableError` propagates and becomes a real
`not_enough_information` with the cause attached.

**Caching.** SHA-256 over agent name + user + claim text + full-pixel image hash + prompt
version + model. Prompt version and model are in the key so changing either invalidates
rather than silently serving stale answers. Redis when `REDIS_URL` is set, in-process dict
otherwise.

---

## 6. Streaming and asynchronous flow

Two contracts coexist during migration.

### 6.1 Blocking SSE — what the UI uses
`POST /claims/submit-multimodal-stream` → `text/event-stream`, one `{stage, status,
timestamp}` frame per stage, terminal `{stage: "done", claim: {...}}`.

The pipeline runs on a **worker thread** feeding a `queue.Queue`; the generator drains it
with a 15s timeout and emits `: keepalive` on expiry. This exists because the gap between
`perception:running` and `perception:complete` *is* the model call — measured at ~9s
normally and **185s under per-minute backoff near the daily cap** — and a reverse proxy
closes a response that has gone quiet (~100s on Render). Database writes stay on the calling
thread: a SQLAlchemy `Session` is not thread-safe.

### 6.2 Async job contract — `/api/v1`
`POST /api/v1/claims` → **202 Accepted** + `Location: /api/v1/jobs/{id}`, then
`GET /jobs/{id}` (poll) or `GET /jobs/{id}/stream` (SSE, same keepalive).

- Executor: `ThreadPoolExecutor(max_workers=4)`. Small on purpose — the ceiling is 5 RPM of
  quota, not CPU. Stated limitation: the brief specified ARQ over Redis; there is no broker,
  and writing code against a Redis that never runs would be worse than saying so. Swapping
  the executor changes `services/jobs.py` and nothing else.
- **The job row is the progress channel** — no broker. Progress must survive a client
  reconnect, so it must be durable, so the database is already the right place.
- `reap_orphans()` at startup fails jobs left `running`; a job stuck forever is worse than
  one that reports honestly it was interrupted.
- **Idempotency-Key**, scoped per user. A replay returns **200**, not 202 — nothing new was
  accepted. Known gap: the column is indexed but not unique, so a true race can double-create.
- **Cursor pagination** on the primary key, not offset: offset re-scans skipped rows and
  silently skips records when rows are inserted mid-page, which for a review queue means a
  claim nobody ever sees.

A subtle SQLAlchemy bug is guarded here: `_record()` builds **fresh dicts** rather than
mutating those already in `job.progress`. A plain JSON column has no mutation tracking, so
mutating in place also mutates the change-detection snapshot, `old == new`, and the UPDATE is
silently dropped — the job completed correctly and reported no progress at all.

---

## 7. Persistence

SQLAlchemy 2.0, **synchronous**, `create_all` (no Alembic yet). SQLite by default; any
SQLAlchemy URL via `DATABASE_URL`.

| Table | Purpose |
|---|---|
| `claims` | The verdict and everything that fed it: policy, perception-derived fields, decision, fraud, user risk, manual override, timestamps |
| `audit_logs` | One row per pipeline stage — `agent_name`, `inputs`, `outputs` (JSON), `reasoning`; cascade-deleted with the claim |
| `jobs` | uuid4 id, status, stage, `progress` JSON, `claim_id` FK, `idempotency_key`, `submitted_payload`, lifecycle timestamps |

Timestamps are stored **naive UTC** so SQLite can compare them, and serialised with an
explicit offset by `UTCTimestamps` (Pydantic `field_serializer`) and `utc_iso()`. Without
that, ECMAScript reads an offset-less string as *local* time and every claim lands hours in
the reader's future.

Two columns are retained but unfed: `impact_direction` and `drivable_status` had no source
in the current perception schema. Kept at defaults so no migration is required and no
consumer breaks.

Sidecar stores outside the RDBMS:

| Store | Path | Contents |
|---|---|---|
| Image index | `.aurelix/image_index.db` (SQLite) | Fingerprints only — never photographs |
| Quota ledger | `.aurelix/quota_state.json` | Per-model daily spend, Pacific-keyed |
| Checkpoint | `.aurelix/checkpoint.db` | Per-claim batch progress for CLI resume |
| Retrieval index | `.aurelix/index/*.json` | Three collections + manifest |

---

## 8. Verdict pipeline

`rules_engine.py`. Given the same perception record this produces the same verdict every
time, and every verdict names the rule that produced it.

**Fraud score** — additive over objective signals only, from `config/decision_rules.yaml`:
`duplicate_image_reuse`, `user_history_risk`, `instruction_like_text`, `poor_image_quality`,
`object_mismatch`, `part_mismatch_with_damage_elsewhere`, `severity_inflation`. Capped at 100.

**Confidence** — documented weighted blend of average visual confidence, effective image
quality, part-match strength, and severity agreement. `severity_delta is None` scores 30
("unmeasurable, not agreeing"), not 100.

**Ordered rules, first match wins.** 15 rules, most-dispositive first:

```
R001 no_usable_image          → not_enough_information
R002 perception_unavailable   → not_enough_information
R010 wrong_object             → contradicted
R003 image_quality_unusable   → not_enough_information
R020 claimed_part_not_visible → not_enough_information
R021 part_never_specified     → not_enough_information
R030 duplicate_image_reuse    → contradicted
R031 high_fraud_score         → contradicted
R040 part_mismatch            → contradicted
R041 no_damage_on_visible_part→ contradicted
R042 severity_inflation       → contradicted
R050 supported_with_overstatement → supported
R051 supported_adjacent       → supported
R052 supported                → supported
R099 indeterminate            → not_enough_information
```

Conditions are a small declarative DSL: `always`, equality, `_in`, `_gte`, `_lte`, with
`None` never matching a numeric comparison.

**Escalation** is computed after the verdict: confidence below 70, verdict in
`always_review_verdicts`, any flag in `always_review_flags`, or fraud ≥ 50.

**Judgement is a pure function of stored perception.** `judge()` takes a stored record and
re-derives the verdict with no network access — which is how rule and ontology fixes are
evaluated across the whole benchmark at zero API cost.

---

## 9. Evidence upload and storage

`platform_backend/services/uploads.py` is the single edge, shared by both submission routes.

1. **Count cap** (`MAX_UPLOAD_FILES`, default 6) → 413.
2. **Byte cap** (`MAX_UPLOAD_BYTES`, default 8 MiB) → 413.
3. **Decompression-bomb guard** — `Image.MAX_IMAGE_PIXELS = 64_000_000`.
4. **Two-pass decode** — `verify()` then reopen and `load()`; truncated files fail here.
5. **Format from `Image.format`**, not from the filename or Content-Type → 415 if outside
   `{JPEG, PNG, WEBP, GIF, BMP}`.
6. **Generated name** — `uuid4().hex` + extension. The client's filename never touches the
   filesystem; a caller who controls the name controls the path.
7. Stored path recorded as a **relative** `uploads/<uuid>.<ext>`, never absolute — the API
   hostname differs per environment and baking one in makes historical rows point at
   whichever environment created them.

Served by a **route**, not a `StaticFiles` mount: a mount binds its directory at import time,
so anything that relocates storage afterwards serves a path that no longer holds the files.
The route rejects any name containing a separator, resolves, and confirms containment within
the upload root before responding with `Cache-Control: immutable`.

Decoding happens at the edge rather than on the worker so a malformed upload fails fast with
a 400 the submitter can act on.

---

## 10. Retrieval, indexing and duplicate detection

Two independent subsystems. **One is in the live request path; one is not.**

### 10.1 Image index — LIVE, in the request path
`retrieval/image_index.py` + `retrieval/hashing.py`. SQLite, linear scan with popcount.

Stores **two 64-bit perceptual hashes (pHash via DCT, dHash) plus a SHA-256 content hash** —
never the photograph. A deliberate privacy property: the index can say "this image was
submitted before, under claim X" without retaining anyone's image, and a leak of the index
leaks no images.

Content hash is over **decoded pixels**, not file bytes, so re-encoding does not demote an
exact match to a judgement call.

Two tiers with different evidential weight: `exact` (identical bytes, no threshold to argue
about) and `near` (both hashes must agree within threshold). Thresholds in
`config/retrieval.yaml` are derived from measured bit distances between real fixture images
and transformed copies of themselves, versus distances between genuinely different images.

Only images passing the quality gate are indexed — a near-featureless image moves 22 pHash
bits under a plain JPEG re-encode, so indexing one manufactures false accusations. The gate
is a precondition of this feature, not a neighbour of it.

This is what makes **`R030_duplicate_image_reuse`** able to fire.

### 10.2 Hybrid text retrieval — BUILT, NOT WIRED INTO THE REQUEST PATH
`retrieval/hybrid.py` + `retrieval/collections.py`. Three collections
(`historical_claims`, `policy_rules`, `fraud_patterns`) built offline by
`tools/build_index.py`, versioned with a manifest, upsert by default.

- Dense arm: **LSA** — TF-IDF then truncated SVD in numpy, L2-normalised so a dot product is
  a cosine. Explicitly not a transformer embedding; `GeminiEmbeddingBackend` implements the
  same interface for when spending request budget on embeddings is authorised.
- Sparse arm: **BM25Okapi** (`rank_bm25`).
- Fusion: **Reciprocal Rank Fusion**. Chosen over a weighted blend because cosine ∈ [-1,1]
  and BM25 is unbounded and corpus-dependent; blending needs a normalisation and a weight
  that must be refitted whenever the corpus changes and never is. RRF needs only ranks.
- Metadata filtering is applied **before** scoring — post-filtering silently returns fewer
  than k results, most often exactly when the corpus is dominated by another category.

**Current wiring:** `IndexBundle.load()` runs at FastAPI startup into `app.state.index`, and
`/ready` reports its status. Nothing reads it during claim analysis. Loading is best-effort
by design — retrieval informs a reviewer, it does not decide anything — but as of today it is
**an available capability, not a live input to any verdict.**

---

## 11. Validation, security and error handling

**Input validation.** Pydantic v2 throughout: request bodies, LLM response schemas, and the
frozen contract vocabularies. `coerce_to_vocabulary()` clamps anything reaching the CSV.

**Prompt injection.** Claim text is treated as untrusted input. The perception schema carries
`instruction_like_text_present`; the model is told to report directives aimed at it and
continue analysing normally. It becomes a fraud signal and a `text_instruction_present` risk
flag, never a control-flow change. Adversarial fixtures live in
`tests/fixtures/adversarial_claims.csv`, and the project rule is that an injection case must
demand a *different* verdict than the true one — otherwise "resisted the injection" is
indistinguishable from "was right by coincidence".

**Never fabricate.** No mock fallback anywhere in the model path. An earlier version caught
every exception and returned `claim_status="supported", confidence=85`.

**CORS.** Two coherent modes. `CORS_ORIGINS=*` allows any origin **with credentials off** —
the spec forbids wildcard + credentials, so the previous configuration was not permissive but
broken, rejected by browsers. An explicit list allows credentials. `CORS_ORIGIN_REGEX` admits
Vercel preview hostnames, which change per push and cannot be enumerated.

**Health.** `/health` does no I/O — a check that touches the database reports the database's
problems as the process's, and the platform restarts a container that was never the problem.
`/ready` checks the database (required), and reports Gemini key and index status without
making them fatal.

**Known gaps** — stated, not hidden:
- **No authentication.** `user_id` is a form field; anyone can submit as anyone and read any
  claim by id. Highest-priority remaining work.
- Uploads are served to anyone holding the URL. UUID names are obscurity, not access control.
- Idempotency has a race window (indexed, not unique).
- Ephemeral storage on free tier.

---

## 12. Deployment architecture

```
Vercel (frontend/)                     Render (repo root)
  Next.js 16, static prerender    ──►    uvicorn, 1 worker, free plan
  NEXT_PUBLIC_API_URL baked at            healthCheckPath: /health
  build time                              build: pip install -r requirements.txt
                                                 python -m agent_core.tools.build_index
```

Ordering matters and is not optional: Render first → Vercel with the API URL → back to Render
to set `CORS_ORIGINS` to the Vercel origin.

- `NEXT_PUBLIC_API_URL` is **inlined at build time**, so changing it needs a redeploy.
- The retrieval index is built during the Render build because `.aurelix/` is gitignored run
  state. It costs no API requests.
- One uvicorn worker: the streaming route holds a worker for the model call, and a second
  worker on 0.1 CPU contends rather than helps. Concurrency belongs to the v1 job pool.
- Free instances sleep after ~15 min idle and take ~50s to wake; the frontend's error text
  says so rather than showing "Failed to fetch".
- Disk is ephemeral. `DATABASE_URL` and `uploads.save_image()` are the two seams for
  Postgres and object storage.

---

## 13. Frontend architecture

Next.js 16.2.12 App Router, React 19.2.4, single static-prerendered route with all state
client-side. `frontend/lib/api.ts` is the only module that knows where the backend lives.

| Component | Responsibility |
|---|---|
| `app/page.tsx` | Shell: sidebar, tab state, selected claim, claim re-fetch on selection |
| `SubmitClaimTab` | 4-step wizard → SSE submission |
| `LiveInvestigationViewer` | Real-time stage graph, evidence pane, verdict summary, raw JSON log |
| `ClaimReviewTab` | Full investigation: intake, evidence images, per-agent timeline, labels |
| `ReviewQueueTab` | Escalated claims, expand-to-act, approve/reject with notes |
| `AnalyticsTab` | Recharts pie/bar/line over `/analytics` |
| `SystemHealth` | Header strip polling `/ready` every 30s |

**Selecting a claim from a list re-fetches it.** List endpoints return `ClaimSchema`, which
carries the verdict but not `audit_logs`; handing a list row straight to the review tab would
render an investigation with an empty agent timeline — the one thing that screen exists for.

**The SSE reader tolerates comment frames**, filtering `data:` lines and skipping empty
frames, so keepalives never reach an event handler. A stream that ends without a terminal
`done` frame throws rather than silently rendering a blank result.

**No `AnimatePresence mode="wait"` in the wizard.** Nesting it inside the page-level one
deadlocked on exit: the outgoing panel never completed, the incoming one never mounted, and
`step` advanced 1→4 invisibly while the screen showed step 1 — the fourth press ran a real
analysis from a form nobody had seen.

---

## 14. Design decisions and why

| Decision | Reason |
|---|---|
| One LLM call, everything else deterministic | 20 requests/day; and a verdict must cite a rule, not a model |
| Model does perception only, never judgement | Both operands of every comparison are already in its own output; asking it to subtract adds a failure mode without adding information |
| Batch size 3, not higher | Quota is not the scarce resource — cross-claim isolation is |
| Isolation validation is fatal | A contaminated verdict is indistinguishable from a good one downstream |
| Quality gate overrides model, one-way only | A model that has committed to a damage finding is the worst judge of whether it could see well enough to make it |
| Judgement as a pure function of stored perception | Rule/ontology fixes evaluate across the whole benchmark at zero API cost |
| Model ladder over a single model | Free quota is per model; three rungs is 60/day free |
| Record-then-refund quota accounting | Under-counting is the expensive direction of error |
| RPD raises, RPM waits | The correct response to the two 429s is opposite |
| Fingerprints, not images, in the index | Duplicate detection without retaining anyone's photograph |
| RRF over weighted blend | No normalisation constant that has to be refitted and never is |
| Job row as progress channel | Progress must survive a reconnect ⇒ must be durable ⇒ the DB already is |
| SSE keepalive | A 185s silence is closed by every reverse proxy |
| Cursor pagination | Offset paging hides claims from a review queue |
| Uploads served by a route | A mount binds its directory at import time |
| LangGraph removed | One call plus straight-line Python has nothing to branch on; a graph framework with no fan-out is a dependency, not an architecture |

---

## 15. Current code vs legacy

**Current production code:** `agent_core/{agents,retrieval,schemas,services,prompts,evaluation,tools}`,
`agent_core/{service,run_pipeline,rules_engine,main}.py`, all of `platform_backend/`,
`frontend/{app,components,lib}`, `config/*.yaml`, `tests/`, `requirements.txt`, `render.yaml`.

**Legacy / dead — not imported by any live module:**

| Path | Status |
|---|---|
| `submission_package/` | The superseded LangGraph architecture — `orchestrator/graph.py`, 11 agents, 4 LLM calls/claim. Referenced by nothing in `agent_core`, `platform_backend`, `tests` or `frontend`. Retained by explicit instruction |
| `frontend/app/page.tsx.bak` | 96 KB snapshot of a previous dashboard |
| `aurelix_agent_core.zip`, `log.txt` | Build artefacts from June |
| `test_db_hang.py`, `test_parse.js` | Root-level scratch files, outside the pytest `testpaths` |
| `scripts/`, `claims/`, `evaluation/` | Superseded by `agent_core/tools`, `agent_core/data`, `agent_core/evaluation` |

`agent_core/main.py` is live but thin — an argparse front for `run_pipeline`.

Also live-but-unused-by-the-UI: `POST /claims/submit` (JSON, no images) and
`platform_backend/services/cache.py`, which only that route calls. The whole `/api/v1`
surface is implemented and tested but the UI still uses the blocking route.
