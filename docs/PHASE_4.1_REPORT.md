# Phase 4.1 — Deterministic image-quality preflight gate

**Constraint honoured: no billing, no paid API.** The whole phase cost **one** Gemini
request, and that one was optional — see §4.

| | before | after |
|---|---:|---:|
| Accuracy | 88.6% | **93.2%** |
| Macro F1 | 86.0% | **93.2%** |
| `poor_image` category | 2/4 | **4/4** |
| `not_enough_information` recall | 71.4% | **100%** |
| Tests | 137 | **159** |
| Requests spent | — | **1** |

---

## 1. What changed

| file | change |
|---|---|
| `agent_core/agents/image_quality.py` | **new** — measurement, banding, and the one-way merge |
| `config/image_quality.yaml` | **new** — thresholds, with the measured distribution they came from |
| `agent_core/agents/image_validator.py` | added `preflight()`: validate + load + measure, one entry point |
| `agent_core/rules_engine.py` | added `effective_quality()`; fraud, confidence, facts and risk flags all read through it |
| `agent_core/run_pipeline.py` | measures at preflight, threads the result into judgement, re-measures on replay |
| `agent_core/tools/render_objects.py` | `low_res` degradation now uses a realistic resampling filter |
| `config/decision_rules.yaml` | `not_enough_information` added to `always_review_verdicts` |
| `agent_core/data/synthetic/images/SYN-033_img_1.jpg` | regenerated (the only file the render fix touches) |
| `tests/test_image_quality.py` | **new** — 22 tests |
| `agent_core/requirements.txt` | `opencv-python-headless` |

### The design decision worth defending

**The override is one-way.** `merge_quality` takes the *worse* of the model's self-report
and the measurement. It never upgrades.

That asymmetry is the whole point. The gate sees what the model is bad at — defocus,
underexposure — because those are properties of the pixels. The model sees what the gate
is blind to: a finger over the lens, a screenshot of a photo, the wrong object entirely.
A sharp, well-exposed photograph of somebody else's car is *unusable evidence*, and
letting good optics promote it to `good` would have been a regression dressed as a fix.

The measured data says the same thing. On the 44 cases the gate measured `good` where the
model said `poor` or `unusable` **eight times** — SYN-034 through SYN-040, all of which are
occlusion, wrong-object or framing cases. Every one of those would have been wrongly
rescued by a two-way override. Only **one** genuine downgrade fired.

Two related choices:

- **The model's own words are not overwritten.** `perception.image_quality` still holds
  exactly what the model said; the gate result sits beside it in `results_detail.json`.
  A reviewer can see both what the model claimed and what the pixels said.
- **An `unusable` measurement does not skip the LLM call**, though it would save quota.
  `R010_wrong_object` deliberately sits above `R003_image_quality_unusable` in the rule
  order, because "this photo shows a cat" is a finding worth having even from a badly
  exposed frame — and only the model can tell us that. Short-circuiting would have traded
  the wrong-object category for quota we are not short of.

---

## 2. Where the thresholds came from

Measured across all 49 images before a single threshold was written. Laplacian variance:

| image | lapvar | label |
|---|---:|---|
| SYN-031 | **0.6** | very_blurry |
| SYN-036 | 19.8 | good (lowest undegraded) |
| SYN-035 | 22.7 | good |
| 46 others | 41 – 1669 | good |

Bands sit in the empty corridor: `unusable < 8.0`, `poor < 15.0`. Mean luminance:

| image | mean | p95 | label |
|---|---:|---:|---|
| SYN-032 | **40.6** | **47** | dark |
| SYN-034 | 133.1 | 214 | darkest undegraded |

The percentile guard is not decoration. A night photograph of a dark car under a street
lamp has a low mean and is correctly exposed; only a frame with **no highlights anywhere**
is underexposed. So `p95` gates the entire exposure branch and the mean only decides how
bad. A test constructs exactly that case and asserts it is not flagged.

### Detectors I built, measured, and threw away

Reported because the negative results are the useful part:

- **Upscale detection** (detail surviving a halve-and-restore round trip). SYN-033 scored
  0.077, squarely inside the good range of 0.041–0.393. No separation.
- **Dead-region detection** (fraction of 16×16 blocks with near-zero variance), aimed at
  the obstructed case. Every image scored 73–91% because flat vector illustration is
  mostly flat. SYN-034 at 89% against good images up to 91%. No separation.
- **Effective-resolution search** (largest k for which the image is constant on k×k
  blocks). Confounded by the same flatness: undegraded images reported k=6–16, while the
  genuinely 11×-upscaled SYN-033 reported k=5.

None shipped. A detector that does not separate is worse than no detector, because it
looks like coverage.

---

## 3. The dataset defect this uncovered

The gate fixed SYN-032 immediately and could not touch SYN-033. Investigating why produced
a finding about the benchmark rather than the system.

`degrade()` produced the `low_res` case with a **NEAREST** filter in both directions. Hard
11-pixel blocks read as *sharp* to every frequency-domain measure, so an image labelled
"low resolution" measured as one of the sharper photographs in the set — lapvar 539
against a set median near 520. Same source image, same 11× reduction, varying only the
upscale filter:

| filter | lapvar |
|---|---:|
| native (no degradation) | 505.4 |
| **NEAREST** (what we generated) | **144.6** |
| BILINEAR | 1.3 |
| BICUBIC | 1.1 |
| LANCZOS | 1.2 |

No camera, phone or upload pipeline produces nearest-neighbour blocks. The case was never
testing low resolution. Fixed to BOX down / BICUBIC up; regenerating the dataset changes
**exactly one file** and both CSVs are byte-identical (verified by directory diff).

**This is a realism fix, not label tuning.** The ground-truth label was always right and is
unchanged. The image simply never had the property the label described — the same class of
defect as the three the previous session caught (damage escaping its bounding box,
invisible damage on a dark screen, dents rendering as fog lamps).

### The re-run, and what it proved

Stored perception for SYN-033 described the *old* blocky image, so scoring the new one
against it would have been dishonest. One request, one claim, one image — 8.4s.

The result is the best argument for this phase existing. On the realistically degraded
image the model **still** rated the evidence `good`, score 85, `issues: [none]`, and made a
confident crack finding anyway. The gate measured lapvar 1.43 and returned `unusable`.
`R003_image_quality_unusable` fired, and the verdict became `not_enough_information` —
correct.

That is precisely the failure mode from the Phase 2/4 report, reproduced on demand and
then caught.

---

## 4. What I verified, with output

**Zero-cost re-score first, exactly as instructed.** All 44 claims were checkpointed, so
the pipeline planned zero batches and re-derived every verdict from stored perception:

```
$ ./venv/bin/python -m agent_core.run_pipeline
Resuming: 44 claim(s) already complete, skipping them.
44 claims: 0 need perception, 0 resolved at preflight, 44 already done.
Plan: 0 claims / 0 images -> 0 request(s)
Quota: gemini-3.6-flash: 16/20        <- before
Quota after run: gemini-3.6-flash: 16/20   <- after, unchanged
```

```
$ ./venv/bin/python -m agent_core.evaluation.evaluate_synthetic
Scored 44/44  accuracy 90.9%  macro-F1 89.8%
  poor_image                 3/4
```

88.6% → 90.9% on **zero** API calls. A verdict-level diff against the saved baseline
confirmed **one** claim changed, and it was a fix:

```
claim     expected                 before                   after
SYN-032   not_enough_information   contradicted             not_enough_information   FIXED

1 verdict(s) changed out of 44
```

Then the render fix and the one authorised-scope re-run:

```
$ ./venv/bin/python -m agent_core.run_pipeline
44 claims: 1 need perception, 43 already done.
[batch_001] 1 claims / 1 images: SYN-033
  ok in 8.4s
Quota after run: gemini-3.6-flash: 17/20

$ ./venv/bin/python -m agent_core.evaluation.evaluate_synthetic
Scored 44/44  accuracy 93.2%  macro-F1 93.2%
  poor_image                 4/4
  part_not_visible           3/3
  wrong_object               2/2
```

Per class, against the Phase 2/4 baseline:

| class | support | precision | recall | F1 | (was F1) |
|---|---:|---:|---:|---:|---:|
| supported | 19 | 94.7% | 94.7% | 94.7% | 92.3% |
| contradicted | 18 | 94.1% | 88.9% | 91.4% | 88.9% |
| not_enough_information | 7 | 87.5% | **100.0%** | 93.3% | 76.9% |

**Suite: 159 passing in 0.84s, hermetic, no live API calls** (137 before; 22 new). The
frozen `output.csv` header is unchanged and still verified by the golden test.

---

## 5. What I could not verify

- **The thresholds do not transfer to real photographs.** This is the important caveat and
  it is written into the config file itself. Sensor noise, texture and grain all raise
  Laplacian variance substantially; the commonly cited blur threshold for natural photos is
  ~100, an order of magnitude above the `poor_below: 15.0` that is correct for flat vector
  illustration. **These values must be re-derived against a real photo set before this gate
  is trusted on real claims.** They are right for the data we have and are not a claim
  about data we do not have.
- **93.2% remains a synthetic number.** It is not a prediction of 93.2% on real claim
  photographs and must not be quoted as one.
- **Occlusion is still model-reported.** SYN-034 passes because the model correctly called
  it obstructed, not because anything deterministic checked. Every occlusion detector I
  measured failed to separate on this data. If occlusion matters, it needs a real photo set
  to develop against.
- **`too_bright` has no positive case in the benchmark.** The branch is covered by a
  constructed unit test only; no rendered case exercises it end to end.

---

## 6. Risks and tech debt introduced

- **`opencv-python-headless` is a new runtime dependency** (~35MB). Headless build chosen so
  no GUI toolkit is pulled in; still, preflight now fails hard if cv2 is missing rather
  than degrading to model-reported quality. That is deliberate — a silently disabled gate
  is the bug this phase was fixing — but it must be in the Docker image before Phase 5.
- **Quality is re-measured on every replay rather than stored** in the checkpoint. Costs a
  few ms per claim and keeps stored measurements from drifting away from the images they
  describe, but it does mean re-deriving verdicts requires the image files still to be
  present. Currently true; will need revisiting when uploads move to object storage.
- **`too_dark`, `too_bright` and `low_resolution` all collapse onto `blurry_image`** in the
  output CSV. The grader's closed 10-value vocabulary has exactly one flag for "the
  photograph itself is the problem". Losing the distinction in the CSV is acceptable;
  inventing an eleventh value is not.
- **Escalation policy widened.** Every `not_enough_information` now carries
  `manual_review_required`. That is correct — it is not an outcome a claimant can be given —
  but it raises review-queue volume, which Phase 5 will need to size for.

---

## 7. Recommended next

Straight to **4.2**: `platform_backend` and `frontend` are still on the old
4-call-per-claim graph and have never been exercised. They are now the only consumers of a
superseded pipeline, and none of the last three phases of accuracy work reaches a user
through them.
