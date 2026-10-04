# AURELIX — Autonomous Trust Intelligence for Damage Claims

[![CI](https://github.com/RajsoniTech13/AURELIX-Autonomous-Claims-Intelligence-Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/RajsoniTech13/AURELIX-Autonomous-Claims-Intelligence-Engine/actions/workflows/ci.yml)

A claims-verification platform where **an LLM only observes, deterministic rules decide, a RAG
copilot explains the insurer's policy with citations, and a human approves edge cases** —
secured with role-based access, measured with offline evaluations in CI, and cost-tracked per
model call, all within free-tier budgets.

A claimant describes what happened and attaches photographs; AURELIX decides whether the
evidence **supports**, **contradicts**, or is **insufficient** for the claim, and names the
rule that made that call. Live demo: **[aurelix.space](https://www.aurelix.space)** (one-click
demo sign-in as a claimant or a reviewer).

---

## How a claim is decided

One multimodal model call, then arithmetic:

```
preflight            deterministic — decode, measure blur/exposure, reject unusable images
duplicate_check      deterministic — perceptual hash against every photograph ever submitted
perception           ONE Gemini call — what is in the images, what does the claimant assert
policy_verification  deterministic — evidence requirements, cited by rule_id
user_risk            deterministic — claim history, velocity
alignment            deterministic — claimed part vs observed part, severity delta
document_check       deterministic — supporting paperwork against the photographs
decision             deterministic — fraud score, confidence, 17 ordered rules
```

**Only `perception` reaches the network.** The model reports observations; it never computes
the fraud score, the confidence, or the verdict. Those are ordinary Python with a `rule_id`
in the justification, so a verdict can be re-derived from stored perception at no API cost —
and every rule maps to the policy clause that justifies it.

A failure never becomes a verdict. If perception is unavailable, the claim returns
`not_enough_information` with the cause attached, rather than a guess dressed as a finding.

## The Policy Copilot

Reviewers ask questions about the policy and get answers that cite its clauses:

- **Retrieval**: BM25 + a local sentence-embedding model (bge-small, via ONNX) fused by
  Reciprocal Rank Fusion, over 35 clause-level chunks of a synthetic policy. Policy only —
  never another claimant's text.
- **A zero-cost gate**: if no clause is close enough, the answer is "not in the policy" with
  no model call.
- **Grounded generation** through a provider-agnostic LLM gateway (Groq free tier first, a
  Gemini model the claim pipeline does not use as fallback).
- **Citation checking**: only clauses that were actually retrieved can be shown; an uncited
  answer is not shown at all.

`GET /api/v1/claims/{id}/explanation` returns the rule that decided a claim and the clauses
behind it — deterministically, with no model at all.

## What is measured

Every figure below comes from a command in this repository.

| | | command |
|---|---|---|
| Claim accuracy | **95.5%** (95% CI 88.6–100%), macro-F1 **95.0%** (86.0–100%) on 44 synthetic cases | `python -m agent_core.evaluation.evaluate_synthetic` |
| Model requests per claim | **1** | `tests/test_llm_telemetry.py` |
| Copilot retrieval | recall@5 **0.961**, nDCG@5 **0.889** (BM25 + LSA before: 0.818 / 0.687) | `python -m agent_core.evaluation.evaluate_rag` |
| Copilot, live end to end | **32/32** answerable questions cited correctly, **8/8** unanswerable refused | `python -m agent_core.evaluation.evaluate_copilot --live` |
| API memory with the embedding model | **287 MB** (Render free tier: 512 MB) | `evaluate_rag` (serving probe) |
| Tests | **546 passing**, 1 skipped (pgvector, needs Postgres); hermetic — no network, no API keys | `python -m pytest` |

The 44 claims are **synthetic renders**, clearly labelled, with ground truth held separate from
anything sent to the model. The accuracy is not an estimate for real photographs: the set has
no lighting, reflection, occlusion or blur variance. The copilot's 40 golden questions and the
policy were written by the same author.

## Security

JWT access tokens (15 min) with rotating, revocable refresh tokens; Argon2id passwords;
claimant / reviewer / admin roles enforced per route; another claimant's claim is a 404;
evidence served only through expiring HMAC-signed URLs; per-account rate limits; security
headers. **[docs/SECURITY.md](docs/SECURITY.md)** maps the system to the OWASP Top 10 for LLM
Applications (2025): for each risk, what is done, what is not, and the test that proves it.

---

## Layout

```
agent_core/           the reasoning engine — shared by the web platform and the batch CLI
  agents/             perception (the one LLM call) + deterministic alignment, policy, risk
  llm/                text-LLM gateway, provider adapters, per-call telemetry and pricing
  retrieval/          hybrid BM25 + embeddings (RRF), vector stores, policy corpus, image index
  copilot.py          the Policy Copilot: retrieve, gate, ground, check citations
  rules_engine.py     the ordered rules that produce a verdict
  service.py          analyse_claim_events() — the single claim entry point
platform_backend/     FastAPI: auth, claims, review queue, analytics, async jobs, metrics
frontend/             Next.js dashboard — sign-in, submit, live trace, case file, copilot
knowledge/policies/   the synthetic policy and its rule-to-clause map
evaluation/rag/       golden questions and retrieval / copilot reports
config/               every threshold, limit, price and model route
docs/                 architecture, security, learning notes, per-phase reports
```

## Running it

```bash
cp .env.example .env                          # add GEMINI_API_KEY (and GROQ_API_KEY for the copilot)
python -m venv venv && ./venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./venv/bin/python -m agent_core.tools.build_index --no-image-index   # offline; downloads the 67 MB embedding model once
./venv/bin/python -m uvicorn platform_backend.main:app --reload --port 8000
```

```bash
cd frontend
cp .env.example .env.local                    # defaults to http://127.0.0.1:8000
npm install && npm run dev                    # http://localhost:3000
```

```bash
./venv/bin/python -m pytest                                        # the whole suite, hermetic
./venv/bin/python -m agent_core.evaluation.evaluate_synthetic      # re-score claims, no API calls
./venv/bin/python -m agent_core.evaluation.evaluate_rag            # retrieval eval, no API calls
```

## Deploying

Backend on Render, frontend on Vercel, both free tier — **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.
`render.yaml` is a ready blueprint. Set `AURELIX_JWT_SECRET` (else every restart signs everyone
out) and `GROQ_API_KEY` (for the copilot) in the Render dashboard.

---

## Constraints worth knowing before reading the code

- **The output contract is frozen.** `agent_core/output/output.csv` column names, order and
  value vocabulary are a locked public schema with a golden-file test.
- **20 model requests per day**, per project per model, resetting at midnight *Pacific*.
  Request count is the scarce resource; the copilot is routed to models the claim pipeline
  does not use, so it can never spend the demo's claim budget.
- **The model never decides.** Nothing the copilot or the gateway returns is read by the rule
  engine.

## Known gaps

- **Ephemeral storage on free tier.** SQLite, uploads, accounts and refresh tokens do not
  survive a redeploy. `DATABASE_URL` and `services/uploads.save_image` are the seams.
- **No Alembic.** New tables deploy via `create_all`; changing an existing table needs a migration tool.
- **In-process rate limits and job pool**, correct for the single deployed worker only.
- **Refresh tokens live in `localStorage`**, because the frontend and API are different sites;
  see `docs/SECURITY.md` §3.

## Documentation

| | |
|---|---|
| [SECURITY.md](docs/SECURITY.md) | threat model, OWASP LLM Top 10 (2025) mapping, proving tests |
| [LEARN/](docs/LEARN/) | one plain-English note per component, with a traced request and a diagram |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | the design and the measurements behind it |
| [FREE_TIER_DESIGN.md](docs/FREE_TIER_DESIGN.md) | how one request per claim is achieved |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Render + Vercel |
| `docs/PHASE_*_REPORT.md` | what changed each phase, and what was left unverified |
