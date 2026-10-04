# Phase 7 — Production AI Engineering: Report

Branch `feat/phase-7-production-ai`, 2026-10-04. Baseline in `docs/PHASE_7_BASELINE.md`
(351 tests, 95.5% / 95.0%). A1–A4 were merged to `main` by the owner after review; this
report covers A1–A5.

## 1. What changed

### A1 — LLM gateway and call telemetry
- `agent_core/llm/`: `LLMGateway`, adapters for Gemini (through the existing client's ledger,
  governor, retry and breaker), Groq and OpenAI (one OpenAI-compatible adapter), and Anthropic
  (optional SDK); one error taxonomy; strict-schema builder; pricing from `config/pricing.yaml`.
- Task routing in `config/limits.yaml` (`text_tasks`, `text_providers`).
- `llm_calls` table, `GET /api/v1/metrics/llm`, a Model usage card in Analytics.
- Telemetry hook on the perception path; perception calls linked to their claim.
- **Fixed:** perception cache key used per-process-salted `hash()`; telemetry collectors did not
  nest; cost rounding lost half of a cheap call.

### A2 — Policy RAG Copilot
- Synthetic policy (35 clauses) and a rule-to-clause map covering all 17 rules, 10 fraud signals
  and 4 evidence checks.
- Clause-level chunks with contextual headers and content hashes in the existing `policy_rules`
  collection; local bge-small embeddings (fastembed/ONNX); `VectorStore` with NumPy and pgvector
  backends; incremental, content-hash re-indexing; the server never embeds the corpus.
- `POST /api/v1/copilot/ask` (gate, grounded prompt, citation validator) and
  `GET /api/v1/claims/{id}/explanation` (deterministic).
- Golden set (40 questions), offline retrieval evaluation, live copilot evaluation.
- Policy Copilot panel and Policy basis list in the case file.

### A3 — Security baseline
- JWT access + rotating, hashed, reuse-detected refresh tokens; Argon2id (OWASP minimum);
  claimant / reviewer / admin roles on every route; cross-user 404; HMAC-signed expiring evidence
  URLs; per-account rate limits; security headers; per-visitor demo accounts.
- Sign-in screen, session restore and refresh, role-aware navigation and wizard.
- **Fixed:** `demo_guard` DST bug; `/api/v1/claims` bypassed the demo cap; a rejected upload used up
  a demo analysis; the legacy server-path submission route is now admin-only.
- `docs/SECURITY.md`: OWASP LLM Top 10 (2025) mapping with proving tests.

### A4 — Evaluation, CI and hygiene
- Bootstrap 95% intervals on the benchmark; `--min-macro-f1` and `--min-recall5` gates.
- `.github/workflows/ci.yml`: tests (Python 3.13), evaluation gates, `pip-audit`, frontend.
- **Fixed:** `pydantic-settings` CVE-2026-58203 (upgrade); the regex injection detector wired in
  as a review signal; unique idempotency keys; queued jobs restarted rather than failed; a job runs
  at most once; reloaded evidence kept its image format; the evaluation report no longer embeds a
  local home path.
- README rewritten with current numbers.

### A5 — Documentation
`docs/DEFENSE_NOTES.md`, `docs/PITCH.md`, `docs/LEARN/` (5 notes and an index), the updated
`docs/INTERVIEW_AUDIT.md` verdict table, this report.

## 2. What was measured (and how)

| measure | result | command |
|---|---|---|
| Tests | 546 passed, 1 skipped (was 351) | `python -m pytest`; GitHub Actions run 37202181086 on Python 3.13 |
| Claim benchmark | 95.5% accuracy (88.6–100%), 95.0% macro-F1 (86.0–100%) — unchanged | `python -m agent_core.evaluation.evaluate_synthetic` |
| Copilot retrieval, shipped config | recall@5 0.961, MRR 0.885, nDCG@5 0.889, not-found LOO 0.925 | `python -m agent_core.evaluation.evaluate_rag` |
| Copilot retrieval, before (BM25 + LSA) | recall@5 0.818, MRR 0.688, nDCG@5 0.687, not-found LOO 0.775 | same |
| Reranker (rejected) | recall@5 0.906, MRR 0.927, nDCG@5 0.885, not-found LOO 0.825, 51 ms | same |
| Copilot live | 32/32 cited correctly, 8/8 refused (5 with zero calls), 0 stripped, 40 calls | `python -m agent_core.evaluation.evaluate_copilot --live` (Groq only) |
| Serving memory | 112 MB without model, 287.3 MB with it | `evaluate_rag` serving probe; ad-hoc `ps` measurement |
| Embedding the corpus in-process | +139 MB | ad-hoc measurement, this session |
| `openai` SDK | +17.6 MB | ad-hoc `ru_maxrss` measurement |
| Live Groq call | 219 in / 55 out tokens, 706 ms, $0.000033 list | one adapter call |
| Injection detector impact | 0 of 44 stored claims changed verdict, fraud or confidence | replay script, this session |
| Idempotency race | 8 concurrent submissions → 1 job | `tests/test_job_lifecycle.py` |
| Dependency audit | 1 CVE found, fixed; now clean | `pip-audit -r requirements.txt` |
| Gemini quota spent in Phase 7 | 0 | `.aurelix/quota_state.json` |

## 3. What was NOT verified

- **Real per-claim cost.** Telemetry records it from live traffic; no real figure exists yet.
- **pgvector backend** against a real Postgres — no instance was available; its test skips.
- **Gemini embeddings** — refused by design without an explicit opt-in; never run.
- **Anthropic and OpenAI adapters** against live APIs — fixture- and SDK-type-tested only.
- **The Gemini flash-lite copilot fallback** on the text request shape — never called live.
- **Python 3.13 locally** — verified only in GitHub Actions.
- **Accuracy on real photographs** — the benchmark is synthetic; the copilot golden set shares an
  author with the policy, and its gate threshold was tuned on the same questions.
- **Multi-worker behaviour** — rate limits, job pool, quota governor and orphan reaping are correct
  for the one deployed worker only.
- **Production environment variables** — whether `AURELIX_JWT_SECRET` and `GROQ_API_KEY` are set on
  Render cannot be seen from outside.

## 4. Risks and debt introduced

- Refresh tokens in `localStorage` (cross-site deployment); fix: API on `api.aurelix.space` + httpOnly cookie.
- Demo sign-in is on by default and any visitor can act as a reviewer — intended for the demo.
- Groq's 8,000 tokens/minute limits the copilot to ~7 questions a minute before falling back.
- The build now downloads a 67 MB model from Hugging Face; if that fails, retrieval degrades to LSA.

## 5. Recommended next step

Phase B, on approval: Postgres (Neon/Supabase) + Alembic + object storage, which removes the
ephemeral-storage and single-worker limits; then a Redis token bucket and ARQ job queue; then the
bounded, read-only Investigator Assistant.
