# AURELIX — Defense Notes

How to explain and defend each part of AURELIX in an interview. For every feature: what it
is, why it is built that way, what was rejected, how it fails, what changes at 100× scale,
the measured numbers (with the command that produced them), and the questions you are
likely to get.

Every number here was produced in the Phase 7 session (2026-10-04) by the command named
next to it. If a number is not here, it was not measured — say so rather than estimate.

---

## 0. The core idea (pre-Phase 7, still the heart of it)

**What.** One multimodal Gemini call per claim *observes* (what's in the photos, what the
claimant asserts). Everything after it is deterministic Python: alignment, fraud score,
confidence, and 17 ordered rules that produce the verdict and name the rule that fired.

**Why.** An insurer must explain a decision ("R040 fired: damage on the rear bumper, claim
named the front"). A model's opinion is not an explanation. Deterministic judgement is also
reproducible and free to re-run: a rule fix is re-scored across the whole benchmark from stored
perception with zero API calls.

**Numbers.** 1 model request per claim (`tests/test_llm_telemetry.py::test_one_claim_is_still_one_request_and_one_record`).
Accuracy 95.5% (95% CI 88.6–100%), macro-F1 95.0% (86.0–100%) on 44 synthetic cases
(`python -m agent_core.evaluation.evaluate_synthetic`). 17 rules, 8 pipeline stages, 1 of which
calls a model.

**Say it like this:** "The LLM only observes. Deterministic rules decide, and every verdict
names the rule that produced it."

---

## 1. LLM gateway and call telemetry (A1)

**What.** `LLMGateway.complete(task, messages, response_model)` — one call signature for every
text task. A per-task *ladder* of providers in `config/limits.yaml` (Groq free tier first, then a
Gemini model perception doesn't use; OpenAI and Claude optional). Each adapter uses its
provider's native structured output and maps errors onto five classes. Every model call — and
every cache hit — writes one telemetry row: tokens, latency, list-price cost, outcome.

**Why.** Feature code should not hard-wire a vendor. Routing is configuration; changing provider
is a YAML edit. Telemetry answers "what does this cost per claim" with rows, not estimates.

**Rejected alternatives.**
- *LangChain / LiteLLM:* a large dependency for ~200 lines of logic, and it would hide the parts
  worth showing (error mapping, ladder, cost).
- *Retrying the same provider:* on a free tier the daily budget is the limit; retrying spends the
  next request too. The ladder *is* the retry policy.
- *Logging prompts for debugging:* telemetry is more widely readable than claims; it stores counts
  and labels only.

**Failure modes.** Every rung rate-limited or out of quota → a typed error, the copilot shows
"no answer model available" with the closest clauses — never a made-up answer. A broken telemetry
listener is logged and ignored; it cannot fail a claim (tested).

**At 100× scale.** Telemetry rows go to a metrics store (OpenTelemetry exporter on the same
`subscribe` hook); the in-memory cache moves to Redis (already supported); per-provider rate
governors move to a shared Redis token bucket; paid tiers become a config change.

**Numbers.**
- Live Groq call: 219 input / 55 output tokens, 706 ms, $0.000033 list price, strict JSON schema
  honoured (one adapter call, 2026-10-04).
- `openai` SDK adds 17.6 MB when loaded (113.2 → 130.8 MB for the whole app).
- Groq free tier for `openai/gpt-oss-20b`: 30 req/min, 1,000/day, **8,000 tokens/min** — the token
  limit binds at ~7 copilot questions a minute (console.groq.com/docs/rate-limits, read 2026-10-04).
- 37 gateway tests, 12 telemetry tests (`pytest tests/test_llm_gateway.py tests/test_llm_telemetry.py`).

**Likely questions.**
1. *Why not call each SDK directly?* Then every feature knows every vendor's errors and JSON mode.
   One gateway, one error vocabulary.
2. *How do you get reliable JSON?* Provider-native constrained decoding (`json_schema` strict,
   `output_config.format`, Gemini `response_schema`) *and* Pydantic validation after.
3. *What if the model returns invalid JSON?* `InvalidResponse`; the gateway tries the next rung.
   Never repaired by guessing.
4. *Why Groq first?* 1,000 free requests/day vs 20 for a Gemini model, and a budget the claim
   pipeline doesn't share.
5. *How do you stop the copilot eating the claim budget?* The Gemini adapter refuses any model on
   perception's ladder. Tested.
6. *How is cost computed on a free tier?* List-price equivalent from `config/pricing.yaml` (dated,
   sourced). Billed cost is $0, and the dashboard says so.
7. *How do you know caching works?* A test runs the real client twice; the fake network is called
   once and the quota ledger moves by one.
8. *Why record a row for a cache hit?* So cache-hit rate is measurable, not assumed.
9. *What's p95 and how do you compute it?* Nearest-rank percentile over recorded latencies of
   successful calls.
10. *What bug did you find here?* The perception cache key used Python's `hash()`, which is salted
    per process — a shared cache could never hit. Now SHA-256, with a test that fails on the old code.

---

## 2. Policy RAG Copilot and explanations (A2)

**What.** Reviewers ask questions about the policy. Hybrid retrieval (BM25 + local bge-small
embeddings, fused by Reciprocal Rank Fusion) over 35 clause-level chunks; a zero-cost "not in the
policy" gate; a grounded prompt with numbered sources and the question fenced as data; a citation
validator that shows only retrieved clauses. Separately, `/claims/{id}/explanation` maps the fired
rule to its clauses with no model at all.

**Why.** A model alone invents policy wording. Retrieval hands it the real clauses; citations let a
person check every answer. Kept out of the verdict path, and reading only the operator's policy —
never another claimant's text, which would reintroduce cross-claim contamination.

**Rejected alternatives.**
- *Fixed-size chunks (500 tokens):* a citation must point at something readable; clause chunks with
  a contextual header ("Part 3 — Exclusions › EXC-2") do.
- *LSA as the dense arm:* measured, much worse (below).
- *A cross-encoder reranker:* measured — raised MRR slightly, lowered recall@5, nDCG and not-found
  accuracy, at 17× the latency and +160 MB. Not used.
- *Gemini embeddings:* would spend the demo's quota. Implemented but refuses without
  `AURELIX_ALLOW_GEMINI_EMBEDDINGS=1`; not measured.
- *pgvector in production:* 35 vectors are fastest scanned exactly in NumPy. pgvector (HNSW,
  cosine, JSONB pre-filter) is implemented behind the same interface for Postgres.

**Failure modes.** Off-policy question → "not in the policy", zero calls. No model available →
closest clauses shown, no answer. Model cites something not retrieved → stripped; nothing valid
left → answer not shown. Embedding model can't load → retriever falls back to LSA instead of failing.

**At 100× scale.** Many policies and tenants → pgvector with a `tenant_id` pre-filter; corpus
versioning per policy edition; embeddings computed by a worker, not the build; a reranker
re-evaluated on a larger golden set; an entailment check of answer text against cited clauses.

**Numbers** (`python -m agent_core.evaluation.evaluate_rag`, 40 golden questions, no API calls):

| | recall@5 | MRR | nDCG@5 | not-found (leave-one-out) | query |
|---|---:|---:|---:|---:|---:|
| BM25 only | 0.828 | 0.712 | 0.711 | 0.825 | 0.1 ms |
| BM25 + LSA (before) | 0.818 | 0.688 | 0.687 | 0.775 | 0.1 ms |
| **BM25 + bge-small (shipped)** | **0.961** | **0.885** | **0.889** | **0.925** | 3.3 ms |
| + cross-encoder rerank | 0.906 | 0.927 | 0.885 | 0.825 | 51 ms |

Live end to end (`python -m agent_core.evaluation.evaluate_copilot --live`, Groq free tier only):
32/32 answerable questions answered citing a correct clause; 8/8 unanswerable refused, 5 by the
gate with zero model calls; 0 citations needed stripping; 40 model calls including 5 injection probes.

Memory: whole API 112 MB without the model, **287.3 MB** with it serving questions; embedding the
corpus inside the server would add ~139 MB — so the build does it, and the server refuses to.

**Likely questions.**
1. *Walk me through a question.* Retrieve top 5 clauses (BM25 + embeddings, RRF) → gate on best
   cosine ≥ 0.60 → grounded prompt → gateway → keep only citations that were retrieved.
2. *Why hybrid?* BM25 nails exact terms ("EVD-1", "deductible"); embeddings catch paraphrase
   ("my car got rusty" → wear and tear). RRF combines rankings without calibrating scores.
3. *Why RRF, not a weighted sum?* Cosine and BM25 are on different scales; RRF needs only ranks —
   one constant, nothing to re-tune.
4. *How did you pick the gate threshold?* Measured: lowest answerable 0.604, highest unanswerable
   0.633 — they overlap. Set at 0.60 so no real question is refused; the model's `not_found` handles
   the borderline ones. Tuned on the same 40 questions — I say that.
5. *How do you evaluate retrieval?* recall@1/3/5, MRR, nDCG@5, and not-found accuracy with a
   leave-one-out threshold, for five configurations.
6. *How do you stop hallucinated citations?* A deterministic validator: a citation must be one of the
   retrieved clause ids, or it's stripped.
7. *Prompt injection in the question?* Fenced as data, forged fence markers stripped, fixed system
   prompt — and the validator, which works even if the model fully obeys the injection (tested).
8. *Why not let RAG inform the verdict?* Verdicts must be reproducible and explainable by a rule; and
   retrieving other claims into a prompt is cross-claim contamination.
9. *Why local embeddings?* Free, offline, no quota, no text leaves the server; 67 MB model, measured
   memory fits the 512 MB instance.
10. *What's weak?* Answer text isn't verified against the cited clause (no entailment check); the
    golden set and policy share an author; the gate threshold overlaps.

---

## 3. Authentication and access control (A3)

**What.** JWT access tokens (HS256, 15 min) and opaque refresh tokens (7 days, SHA-256-hashed,
rotated on every use, family revoked on reuse). Argon2id passwords at the OWASP minimum.
Roles: claimant (own claims only), reviewer and admin (everything, review queue, copilot,
analytics). Another claimant's claim is a 404. Evidence served by expiring HMAC-signed URLs.
Per-account rate limits; security headers. One-click demo sign-in creates a fresh account per visitor.

**Why.** Before, `user_id` was a form field: anyone could submit as anyone, read any claim by id,
fetch any photo, and drain the copilot's quota. And every visitor shared one claim list.

**Rejected alternatives.**
- *Server sessions:* every request would need a database read; JWTs don't. Cost: no early revocation
  — hence 15 minutes.
- *httpOnly refresh cookie:* stronger, but the frontend (Vercel) and API (Render) are different
  sites, where browsers block such cookies. Correct choice once the API is on `api.aurelix.space`.
- *Default demo passwords:* anyone could read them on GitHub. Demo accounts have no password at all.
- *A shared demo claimant:* visitors would see each other's claims again.
- *An "auth off in tests" switch:* tests mint real tokens with the same function login uses.

**Failure modes.** Expired token → silent refresh and retry; refresh fails → sign-in screen.
Missing `AURELIX_JWT_SECRET` → random per-process key: everyone signs in again after a restart,
never a forgeable default. Reused refresh token → whole session revoked.

**At 100× scale.** Managed identity (OIDC/SSO), MFA for reviewers, httpOnly cookies on a shared
domain, Redis-backed rate limits across workers, a revocation list or short-lived tokens with
introspection, audit of every reviewer action (already recorded with the reviewer's name).

**Numbers.** 60 auth tests (`pytest tests/test_auth.py`): 401 on 14 protected routes, forged /
expired / `alg: none` / wrong-type tokens rejected, 403 for the wrong role, cross-user 404s, signed
URL tampering and expiry, refresh rotation and reuse, rate limits. Two mutation checks: removing the
ownership check, or the link-expiry check, fails the tests. Argon2id `m=19456, t=2, p=1`
(OWASP Password Storage Cheat Sheet, read 2026-10-04).

**Likely questions.**
1. *401 vs 403 vs 404?* Unknown caller / known but not allowed / not yours, and we won't confirm it exists.
2. *Why pin the JWT algorithm?* Accepting the token's own `alg` header is how `alg: none` forgeries pass.
3. *How does refresh-token reuse detection work?* Each refresh revokes the old token; presenting a
   revoked one means a copy exists, so the whole family is revoked.
4. *Why Argon2id?* Memory-hard, so GPU guessing is expensive. 19 MiB is the OWASP minimum; the 64 MiB
   default is too much per login on 512 MB.
5. *Why hash refresh tokens with SHA-256, not Argon2?* They're 32 random bytes — not guessable, so a
   fast hash is enough; Argon2 protects low-entropy passwords.
6. *How are images protected if `<img>` can't send a header?* Signed URLs: HMAC over file name and
   expiry, minted only after the ownership check, 15-minute lifetime.
7. *How do you prevent user enumeration?* One error message for every sign-in failure, and a dummy
   hash for unknown usernames so timing matches.
8. *Where are tokens stored, and the risk?* Access token in memory; refresh token in localStorage
   (XSS risk). Mitigated by no HTML rendering, rotation, reuse detection. Cookie is the upgrade.
9. *How do you test auth without disabling it?* Mint real tokens in tests; no bypass flag exists.
10. *What's still weak?* Access tokens can't be revoked early; rate limits are per process; the
    public demo lets any visitor act as a reviewer — by design, with an off switch.

---

## 4. Evaluation, CI and hygiene (A4)

**What.** Bootstrap 95% confidence intervals on the benchmark; GitHub Actions running tests on
Python 3.13, a macro-F1 floor, a retrieval recall@5 floor, `pip-audit`, and frontend
lint/type-check/build. Audit fixes: the regex injection detector wired in as a review signal;
unique idempotency keys; queued jobs restarted instead of failed; each job runs at most once.

**Why.** A single accuracy number on 44 cases hides how uncertain it is. Gates stop a regression
reaching the live site. The audit fixes close gaps an interviewer could find by reading the code.

**Rejected alternatives.**
- *Gate at the measured value:* fails on noise. Floors sit 2–6 points below measured.
- *Live model calls in CI:* would spend the shared demo budget and fail for network reasons.
- *Deleting the regex detector:* the model can miss an injection; a free deterministic check that can
  only route to a human is defence in depth.

**Failure modes.** A regression below a floor → red CI, nothing merged. A known CVE → red CI
(found one: `pydantic-settings` CVE-2026-58203, fixed by upgrading).

**At 100× scale.** A larger, external golden set with per-category floors; eval results tracked over
time; a lockfile with hashes; nightly live evals against a budgeted key.

**Numbers.** Accuracy 95.5% (88.6–100%), macro-F1 95.0% (86.0–100%), 10,000 resamples, seed 7
(`evaluate_synthetic`). CI run on `main` 2026-10-04: all four jobs green, 546 passed / 1 skipped on
Python 3.13 (GitHub Actions run 37202181086). Replaying all 44 stored claims after wiring the injection
detector: 0 verdict, fraud-score or confidence changes. 8 concurrent identical submissions → 1 job
(`tests/test_job_lifecycle.py`).

**Likely questions.**
1. *What does the interval mean?* How much the scores would move on another 44 synthetic cases like
   these — not accuracy on real photos.
2. *Why bootstrap?* Macro-F1 has no simple standard error; resampling works for any metric.
3. *Why a 0.93 floor?* Measured 0.950; fail only on a drop of more than two points.
4. *Why doesn't CI call the model?* Shared free budget, and network flakiness unrelated to the change.
5. *What did the injection detector change?* Only routing: a matched claim goes to a human. Proved by
   replaying 44 claims with zero verdict changes.
6. *How do you make idempotency race-safe?* A unique index on (user, key); the losing insert gets
   the winner's job.
7. *What happens to jobs when the server restarts?* Running ones are failed honestly; queued ones
   restart from saved evidence; an atomic claim stops a job running twice.
8. *What bug did the tests find?* Reloaded images lost their format, so a restarted claim would have
   been "no usable image".
9. *How did you check CI before pushing?* A clean export, fresh venv from requirements only, fresh
   `npm ci` — all green before the first real run.
10. *What's not in CI?* Live model behaviour, pgvector (no Postgres in the runner), memory limits.
