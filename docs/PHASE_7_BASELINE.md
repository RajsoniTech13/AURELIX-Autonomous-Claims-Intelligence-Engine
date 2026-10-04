# Phase 7 — Baseline

Recorded 2026-10-04 on branch `feat/phase-7-production-ai`, at commit `eadba43`
(`feat(demo): add per-visitor capacity guard for the public demo`), before any Phase 7 change.
Every number below comes from the command printed next to it.

## Tests

`./venv/bin/python -m pytest -W ignore`

```
351 passed in 4.91s
```

All hermetic: no live API calls. Per file (`pytest --collect-only`):

| file | tests | | file | tests |
|---|---:|---|---|---:|
| test_ontology_scoping.py | 36 | | test_dataset_integrity.py | 15 |
| test_retrieval.py | 35 | | test_backend_pipeline.py | 14 |
| test_rules_engine.py | 34 | | test_output_contract.py | 13 |
| test_resilience.py | 28 | | test_batch_isolation.py | 13 |
| test_policy_and_contract_wording.py | 27 | | test_uploads.py | 11 |
| test_pipeline.py | 24 | | test_job_api.py | 11 |
| test_image_quality.py | 22 | | test_no_fabrication.py | 9 |
| test_collections.py | 20 | | test_deploy_safety.py | 9 |
| test_document_check.py | 17 | | test_stream_keepalive.py | 5 |
| | | | test_resume_rederives_output.py | 4 |
| | | | test_analytics_consistency.py | 4 |

## Synthetic benchmark (re-scored from stored perception, zero API calls)

`./venv/bin/python -m agent_core.evaluation.evaluate_synthetic`
(writes `agent_core/output/evaluation_report.md`; re-running it left `git status` clean)

| metric | value |
|---|---:|
| Cases scored | 44 / 44 |
| Accuracy | **95.5%** (42/44) |
| Macro-F1 | **95.0%** |
| Weighted F1 | 95.4% |
| Mean confidence | 70 |
| Mean fraud score | 20 |

| class | support | TP | FP | FN | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| supported | 19 | 19 | 1 | 0 | 95.0% | 100.0% | 97.4% |
| contradicted | 18 | 16 | 0 | 2 | 100.0% | 88.9% | 94.1% |
| not_enough_information | 7 | 7 | 1 | 0 | 87.5% | 100.0% | 93.3% |

The two misses are `part_mismatch` 6/7 and `severity_inflation` 4/5. Every other category
scores 100%.

These 44 cases are **synthetic renders**. The figure does not predict accuracy on real
photographs.

## Shape of the system

| fact | value | command |
|---|---|---|
| Decision rules | 17 | `len(yaml.safe_load(open('config/decision_rules.yaml'))['rules'])` |
| Pipeline stages | 8 | `len(agent_core.service.PIPELINE_STAGES)` |
| Stages that call a model | 1 (`perception`) | `agent_core.service.LLM_STAGES` |

## Quota before Phase 7

`python -c "from agent_core.services.gemini_client import quota_summary; print(quota_summary())"`

```
gemini-3.6-flash: 0/20  gemini-3.5-flash: 0/20  gemini-2.5-flash: 0/20
```

Phase 7 runs no live model calls unless explicitly approved.

## Where the prompt and the repo disagree (reality wins)

1. **Two evidence-requirement CSVs, and they differ.** `claims/evidence_requirements.csv`
   requires 2 car photographs. `agent_core/data/evidence_requirements.csv` requires 1. Only
   the second is read by code (`policy_verification.py`, `build_index.py`,
   `platform_backend/config.py`). **Decision (owner, 2026-10-04): the policy corpus follows
   the live `agent_core/data` file.**
2. `prompts/templates.py` is at `agent_core/prompts/templates.py`.
3. `evaluate_synthetic` writes `agent_core/output/evaluation_report.md`. `evaluation/` is
   listed as legacy in `docs/SYSTEM_DESIGN.md` §15, so A4's confidence intervals go into the
   live report.
4. `README.md` is stale: it says 254 tests and 93.2% accuracy. `SYSTEM_DESIGN.md` and
   `INTERVIEW_AUDIT.md` say 15 rules and 7 stages. The actual figures are 351, 95.5%, 17 and 8.
5. Local Python is 3.14.2, while Render pins 3.13.4 (`render.yaml`). Any new binary
   dependency must install on both.

## Bugs found while reading (not yet fixed)

| bug | evidence | consequence |
|---|---|---|
| Perception cache key uses Python's `hash()` (`agents/perception.py`, `run_batch_perception`) | the same string hashed in two processes gave `7322767832648209518` and `-8477028355696975428` | a cached perception can only hit inside the process that wrote it, so a shared Redis cache can never hit |
| `demo_guard` uses a fixed UTC−8 offset | at 2026-10-04 under PDT it reported a reset at `2026-10-04T08:00Z`, which had already passed; the real reset is `2026-10-05T07:00Z` | for one hour a day during daylight saving it is on a different day from the quota ledger, and the reset time it shows is wrong |
| `demo_guard.consume` runs before upload validation (stream route) | read of `routes.py` | a rejected upload still uses up one of a visitor's analyses |
| `/api/v1/claims` is not guarded by `demo_guard` | read of `v1.py` | the per-visitor cap can be bypassed |
| `/claims/submit-multimodal` checks the cap but never consumes it | read of `routes.py` | that route is effectively uncapped |
| `reap_orphans` fails `queued` jobs as well as `running` ones (already listed in A4) | `services/jobs.py` | wrong as soon as a second process exists |
| `jobs.idempotency_key` is indexed but not unique (already listed in A4) | `db/models.py` | a true race can create two jobs |
