# AURELIX — Autonomous Trust Intelligence for Damage Claims

A multi-agent claims verification engine. A claimant describes what happened and attaches
photographs; AURELIX decides whether the evidence **supports**, **contradicts**, or is
**insufficient** for the claim, and says which rule made that call.

Two front doors, one reasoning path: a batch CLI for evaluation, and a FastAPI + Next.js
platform for a person submitting a single claim. Both run the same perception and the same
deterministic judgement — deliberately, so the benchmark measures what production does.

**Runs permanently within the Gemini free tier.** That is an architectural constraint, not
a cost preference, and it shaped most of what follows.

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
decision             deterministic — fraud score, confidence, ordered rules
```

**Only `perception` reaches the network.** The model reports observations; it never computes
the fraud score, the confidence, or the verdict. Those are ordinary Python with a `rule_id`
in the justification, which is why a verdict can be re-derived from stored perception at no
API cost — and why the reasoning survives review.

A failure never becomes a verdict. If perception is unavailable — quota exhausted, malformed
response — the claim returns `not_enough_information` with the cause attached, rather than a
guess dressed as a finding.

## What is measured

| | |
|---|---|
| Accuracy | **93.2%** on 44 cases, macro-F1 93.2% |
| Requests per claim | **1** |
| Latency | ~9s (up to ~185s under per-minute backoff near the daily cap) |
| Tests | **254**, hermetic — no live API calls |

The 44 cases are **synthetic renders**, clearly labelled as such, with ground truth held
separate from anything sent to the model. That accuracy is not an estimate for real
photographs: the set has no lighting, reflection, occlusion or blur variance.

---

## Layout

```
agent_core/           the reasoning engine — shared by both front doors
  agents/             perception (LLM) + alignment, policy, user_risk, image_quality (not)
  retrieval/          hybrid BM25 + dense with RRF fusion; perceptual image index
  rules_engine.py     the ordered rules that produce a verdict
  service.py          analyse_claim_events() — the single entry point
platform_backend/     FastAPI: claims, review queue, analytics, async jobs
frontend/             Next.js dashboard — submit, live trace, investigation, queue
config/               every threshold and magic number
docs/                 architecture, audit, per-phase reports, deployment
```

## Running it

```bash
cp .env.example .env                          # add GEMINI_API_KEY
python -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python -m agent_core.tools.build_index    # offline, costs nothing
./venv/bin/python -m uvicorn platform_backend.main:app --reload --port 8000
```

```bash
cd frontend
cp .env.example .env.local                    # defaults to http://127.0.0.1:8000
npm install && npm run dev                    # http://localhost:3000
```

```bash
./venv/bin/python -m pytest                              # 254 tests
./venv/bin/python -m agent_core.evaluation.evaluate_synthetic   # re-scores stored perception
```

Batch mode over a CSV:

```bash
./venv/bin/python -m agent_core.run_pipeline
```

## Deploying

Backend on Render, frontend on Vercel, both free tier —
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. `render.yaml` is a ready blueprint. The order
matters: each side needs the other's URL, and the frontend bakes its copy in at build time.

---

## Constraints worth knowing before reading the code

- **The output contract is frozen.** `agent_core/output/output.csv` column names, order and
  value vocabulary are a locked public schema with a golden-file test. If it fails, the code
  is wrong.
- **20 model requests per day**, per project per model, resetting at midnight *Pacific*.
  Rotating keys does not reset it. Request count is the only scarce resource here — image
  resolution is not, since image tokens are flat with respect to it.
- **No LangGraph.** It orchestrated a ten-node graph with four LLM calls per claim. That
  pipeline is now one call followed by straight-line Python, and a graph framework with
  nothing to branch on is a dependency, not an architecture. Removed in Phase 4.3; the
  measurement that it *did* run parallel edges concurrently still stands in
  `docs/ARCHITECTURE.md`.

## Known gaps

- **No authentication.** `user_id` is a form field; anyone can submit as anyone and read any
  claim by id. Highest-priority remaining work.
- **Ephemeral storage on free tier.** SQLite and uploaded photographs do not survive a
  redeploy. `DATABASE_URL` and `services/uploads.save_image` are the two seams.
- **No Docker, no Alembic.** Schema changes still go through `create_all`.
- Two submission contracts coexist during migration — the blocking one the UI uses, and the
  v1 async 202/poll/SSE one.

## Documentation

| | |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | the design and the measurements behind it |
| [FREE_TIER_DESIGN.md](docs/FREE_TIER_DESIGN.md) | how one request per claim is achieved |
| [AUDIT.md](docs/AUDIT.md) | what was wrong, found by measurement |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Render + Vercel |
| `docs/PHASE_*_REPORT.md` | what changed each phase, and what was left unverified |
