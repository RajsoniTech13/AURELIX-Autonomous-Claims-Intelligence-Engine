# Phases 2 & 4 — Batched free-tier inference, and the synthetic benchmark

**Constraint honoured: no billing, no paid API, no quota circumvention.**
The full 44-claim benchmark ran on **16 requests** of `gemini-3.6-flash`, against a free
daily budget of 20.

---

## 1. Batch API: tested once, as authorised

```
client.batches.create(model="gemini-3.6-flash", src=[...2 inlined requests...])
-> 400 FAILED_PRECONDITION
```

That is the signature of a billing-gated feature. **No free capacity there.** Testing
stopped immediately, per instruction. The request was rejected at submission, so it did not
consume generation quota.

---

## 2. What was built

| | before | after |
|---|---:|---:|
| LLM calls per claim | 4 | **⅓ of one** |
| Requests for 44 claims | 176 | **15** |
| Fits 20 RPD free budget | no | **yes** |
| LLM decides the verdict | yes | **no** |
| Resumable | no | **yes** |

### The four calls that were replaced

| # | Was | Now |
|---|---|---|
| 1 | `claim_ingestion.py:35` — `ClaimIngestionOutput` | folded into one perception call |
| 2 | `vision_analysis.py:98` — `VisionAnalysisOutput` | folded into one perception call |
| 3 | `fraud_review.py:44` — `FraudReviewOutput` | **deterministic Python** |
| 4 | `decision.py:49` — `DecisionOutput` | **deterministic Python** |

Image quality was already deterministic (`image_validator.py`, Phase 0.5), so it never was
a fifth call.

### Flow

```
44 claims → preflight (deterministic) → scheduler (3 claims/batch)
   → 15 × ONE multimodal request → structured evidence per claim_id
   → isolation validation → alignment → rules → verdict + rule_ids → checkpoint
```

---

## 3. Measurements that shaped the design

All obtained with `countTokens`, which is a separate API action and spends no generation
budget.

**Image tokens are flat with respect to resolution.** Same photo, resized:

| longest side | 3.6-flash | 2.5-flash |
|---:|---:|---:|
| 2048 px | 1089 | 258 |
| 512 px | 1089 | 258 |
| 64 px | 1089 | 258 |

A thumbnail costs exactly what a full-resolution photo costs. Downscaling saves upload time,
**not tokens** — so the brief's premise that downscaling buys batching headroom is false for
these models. The practical consequence is good news: image quality never has to be traded
for quota.

**Tokens are not binding.** A 12-claim, 24-image batch is 28,846 tokens — 2.8% of the
context window, 11.5% of TPM. Only RPD is scarce, which is why the scheduler budgets
*requests* and *image counts*, not bytes.

**Quota is per model**, so the fallback ladder is free capacity rather than a nicety.
`gemini-2.5-flash-lite` is deliberately **excluded**: it returns 404 NOT_FOUND for this
batched multimodal + `response_schema` shape. Measured, not assumed — it failed all 13 times
it was reached during the first run.

---

## 4. Claim isolation

Batching trades a quota problem for a contamination risk. Defended in four layers, of which
only the last does not depend on the model's cooperation:

1. Each claim fenced: `=== CLAIM SYN-007 BEGIN ===` … `END ===`.
2. Every image immediately preceded by `[SYN-007 image img_2]`; numbering restarts per claim.
3. Explicit instruction, verbatim as specified.
4. **Post-hoc validation.** Every requested id present exactly once, no unexpected ids, and
   no `supporting_image_id` outside that claim's own range. A violation rejects the whole
   batch rather than trusting it — a contaminated verdict is worse than none, because
   downstream it is indistinguishable from a good one.

**Result: zero isolation failures across 15 live batches / 44 claims.** 13 unit tests cover
the failure modes directly, including a claimant attempting to forge a block delimiter.

---

## 5. Quota handling

| Failure | Classification | Action |
|---|---|---|
| 429, `...PerMinute...` | transient | backoff + retry |
| 429, `...PerDay...` | **RPD exhausted** | stop model, advance ladder, else checkpoint and exit |
| 503 / 500 | server declined | retry, then next model; **request refunded** |
| 400 / 403 / 404 | rejected outright | fail fast; **request refunded** |

Two bugs found and fixed by running it for real:

- **The ledger counted requests the server never processed.** A model that 404s on every
  call silently consumed 13 slots of recorded budget. Refunds now cover 4xx and 5xx.
- **The ledger reset on UTC midnight**, which arrives 7–8 hours *before* the Pacific reset
  Google actually uses — the ledger zeroed itself while real quota was still spent. Observed
  live: a run recorded 20/20, and an hour later the next run believed the budget was
  untouched. Now keyed on `America/Los_Angeles`.

Retries were reduced from 4 to 2: with a working ladder, failing over to a healthy model
beats grinding on an overloaded one. `gemini-3.6-flash` returned "high demand" 503s on every
attempt during the first run.

---

## 6. Checkpointing

SQLite, one row per claim, committed per batch and atomically. Demonstrated live rather than
asserted:

```
Resuming: 42 claim(s) already complete, skipping them.
44 claims: 2 need perception, 42 already done.
[batch_001] 2 claims / 2 images: SYN-043, SYN-044
```

Two claims re-run cost **one** request instead of fifteen.

A defect surfaced here too: after a resume, `results_detail.json` contained only the newly
processed claims. The fix is the practical payoff of keeping judgement out of the model —
alignment and the rules are a pure function of stored perception, so the other 42 were
**re-derived at zero API cost**. Later scoring iterations reused that: two ontology fixes
were evaluated across all 44 claims without a single additional request.

---

## 7. The synthetic dataset

**44 cases. Clearly labelled SYNTHETIC DEVELOPMENT/EVALUATION DATA.** Narratives are
invented; images are procedurally rendered by `agent_core/tools/render_objects.py`.

| verdict | n | | category | n |
|---|---:|---|---|---:|
| supported | 19 | | match | 14 |
| contradicted | 18 | | part_mismatch | 7 |
| not_enough_information | 7 | | severity_inflation | 5 |
| | | | poor_image | 4 |
| | | | adjacent_part / part_not_visible | 3 / 3 |
| | | | wrong_object (+document) | 2 / 1 |
| | | | no_damage / injection | 2 / 2 |

Not fraud-heavy: honest claims are the plurality, because a benchmark where most cases are
fraudulent teaches a system to be suspicious rather than accurate.

**Ground truth is in a separate file and never enters a prompt.** 15 tests enforce this,
including that narratives never contain a verdict word and that image filenames encode no
labels.

Three defects were caught while building it, each of which would have corrupted the
measurement:

1. **Damage escaping its bounding box** — an unclipped crack spilled off a laptop screen, so
   the "damaged part" label no longer described where damage appeared.
2. **Invisible damage** — dark crack ink on a black screen rendered nothing. Ink is now
   chosen against the surface underneath.
3. **Dents that read as fog lamps** — smooth concentric ellipses on a bumper were reported
   as "no damage visible" in three honest cases. Now irregular blobs with radiating creases.

A fourth was caught by a test: **an injection case demanding the outcome that was already
correct** cannot distinguish resisting the attack from obeying it and getting lucky. Both
injection payloads now demand the *wrong* verdict.

---

## 8. Results

Full report: `agent_core/output/evaluation_report.md`.

| metric | value |
|---|---:|
| Cases scored | **44 / 44** |
| Accuracy | **88.6%** |
| Macro F1 | **86.0%** |
| Requests used | **16** of 20 free |
| Isolation failures | **0** |

| class | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| supported | 19 | 90.0% | 94.7% | 92.3% |
| contradicted | 18 | 88.9% | 88.9% | 88.9% |
| not_enough_information | 7 | 83.3% | 71.4% | 76.9% |

| category | score | |
|---|---:|---|
| adjacent_part | 3/3 | |
| part_not_visible | 3/3 | the distinction the system exists for |
| wrong_object (+doc) | 3/3 | |
| no_damage | 2/2 | |
| injection (both) | 2/2 | resisted, flagged, analysed normally |
| match | 13/14 | |
| part_mismatch | 6/7 | |
| severity_inflation | 4/5 | |
| poor_image | 2/4 | weakest area |

### Progression

| run | change | accuracy | macro-F1 |
|---|---|---:|---:|
| 1 | first end-to-end | 68.2% | 67.1% |
| 2 | severity scale, rule order, ontology, dent rendering | 84.1% | 81.4% |
| 3 | two further ontology fixes (**zero API calls**) | **88.6%** | **86.0%** |

Tuning stopped here deliberately. Further adjustment against 44 synthetic cases would be
fitting noise.

---

## 9. Notable failures

| claim | expected | got | diagnosis |
|---|---|---|---|
| SYN-032, SYN-033 | not_enough_information | contradicted / supported | **The weakest area.** The model judged a low-resolution and an obstructed image usable and made findings anyway. The rules trusted its quality call. A deterministic blur/exposure gate in preflight — Laplacian variance, already designed in `ARCHITECTURE.md` §3.2 — would override an over-confident quality assessment. |
| SYN-029 | contradicted | supported | Narrative said "extensive damage" (rank *high*); the model read it as *medium*, so Δseverity was 1 instead of 2 and it fell one notch below the inflation threshold. Genuinely borderline. |
| SYN-014 | supported | contradicted | Model located a package-side scratch on `quarter_panel`. An ontology gap, not a reasoning error. |
| SYN-021 | contradicted | not_enough_information | **My label is the questionable one.** The claim names the front bumper; the photo is a rear view. The model said the front bumper is not visible — which is true. `not_enough_information` is arguably *more* defensible than the `contradicted` I labelled it. Reported rather than "fixed", because tuning the system to match a doubtful label is how benchmarks stop meaning anything. |

---

## 10. What I could not verify

- **Real-world accuracy.** These are clean vector illustrations. Real claim photographs bring
  lighting, reflections, motion blur, occlusion, dirt, and damage that does not look like a
  drawn shape. **88.6% here is not a prediction of 88.6% on real claims** and should never be
  quoted as one.
- **Batch size 3 versus 2.** Zero isolation failures at 3 is evidence it is safe on *this*
  data; denser or more visually similar batches could behave differently.
- **Sustained multi-day resumption.** Resume was verified within one quota day, not across a
  real reset boundary.
- **`platform_backend` / `frontend`** still call the old per-claim graph. They were not
  migrated to the batched path and were not exercised.

## 11. State of the suite

**137 tests, all passing, no live API calls.** New: 34 rule-engine, 15 dataset-integrity,
13 batch-isolation.

## 12. Recommended next

1. **Deterministic image-quality gate in preflight** (OpenCV Laplacian variance). Directly
   targets the weakest category, and removes a judgement the model should not be trusted with.
2. **Migrate `platform_backend` to the batched path** — it is now the only consumer of the
   superseded per-claim graph.
3. **Phase 3 retrieval** and pHash duplicate detection: `R030_duplicate_image_reuse` exists in
   the rules and nothing can currently trigger it.
