# Free-Tier Batched Inference — measurements and change proposal

**Constraint: no billing, ever. The 44-claim benchmark must run inside the free quota.**

This supersedes §4 of `ARCHITECTURE.md`, which concluded the batch was unreachable on free
tier. That conclusion assumed one request per claim. With batched multimodal inference it is
not just reachable — it is comfortable. Details below, all measured against the live API.

---

## 1. What I measured

`countTokens` is a distinct API action from `generateContent`, so every number here was
obtained **without spending any of the 20 RPD generation budget.**

### 1.1 `gemini-3.6-flash` exists and is suitable

```
gemini-3.6-flash   input 1,048,576   output 65,536
                   generateContent, countTokens, createCachedContent, batchGenerateContent
```

Multimodal input and `response_schema` structured output are both supported by the installed
`google-genai` 2.9.0. **Adopted as primary**, as instructed.

### 1.2 Image tokens are FLAT with respect to resolution

This is the finding that changes the plan. Same photograph, resized, token cost measured:

| longest side | 3.6-flash | 2.5-flash | 2.5-flash-lite |
|---:|---:|---:|---:|
| 2048 px | 1089 | 258 | 258 |
| 1024 px | 1089 | 258 | 258 |
| 512 px | 1089 | 258 | 258 |
| 128 px | 1089 | 258 | 258 |
| 64 px | 1089 | 258 | 258 |

**Downscaling an image does not reduce its token cost. Not slightly — not at all.**

This contradicts the master brief §2.5 ("downscale longest side to ~1024px… cuts image tokens
and upload time dramatically"). It cuts **upload bytes and latency** — 173 KB → 59 KB at
512 px, which is real and worth doing — but the token accounting is unaffected. Any batch
sizing built on "smaller images = more claims per request" would have been built on a false
premise.

Cost is per *image*, essentially flat across aspect ratios too (1064–1100 tokens for
non-square).

### 1.3 Tokens are not the binding constraint. At all.

Batch of N claims, 2 images each, ~6 KB system prompt, on `gemini-3.6-flash`:

| claims | images | tokens | % of 250K TPM | % of 1M context |
|---:|---:|---:|---:|---:|
| 1 | 2 | 3,786 | 1.5% | 0.4% |
| 3 | 6 | 8,307 | 3.3% | 0.8% |
| 5 | 10 | 12,984 | 5.2% | 1.2% |
| 8 | 16 | 19,798 | 7.9% | 1.9% |
| 12 | 24 | 28,846 | 11.5% | 2.8% |

Even a 12-claim batch uses under 3% of the context window. All 44 claim texts combined are
2,816 tokens.

**The only scarce resource is RPD.** TPM, context, and output limits have one to two orders
of magnitude of headroom.

### 1.4 Quota is per-model — which gives a free fallback ladder

Your AI Studio figures show each model carrying its *own* 20 RPD:

| model | RPM | RPD | your usage today | tokens/image |
|---|---:|---:|---|---:|
| `gemini-3.6-flash` | 5 | 20 | 7/20 → **13 left** | 1089 |
| `gemini-2.5-flash` | 5 | 20 | 23/20 → **exhausted** | 258 |
| `gemini-2.5-flash-lite` | 10 | 20 | 0/20 → **20 left** | 258 |

The installed SDK also exposes `gemini-3.5-flash`, `gemini-3.1-flash-lite`, and
`gemini-flash-latest`, each presumably with its own free bucket.

**This is worth more than any batching optimisation.** Three models is 60 requests/day
without paying anything. It turns RPD exhaustion from a hard stop into a rung on a ladder,
and it means retries need not compete with primary traffic.

---

## 2. Where the four LLM calls happen today

Exactly four, all reached from `agent_core/orchestrator/graph.py`:

| # | Call site | Graph node | Model call | Output schema |
|---|---|---|---|---|
| 1 | [`agents/claim_ingestion.py:35`](../agent_core/agents/claim_ingestion.py#L35) | `node_claim_ingestion` (graph.py:185) | `call_gemini_text` | `ClaimIngestionOutput` |
| 2 | [`agents/vision_analysis.py:98`](../agent_core/agents/vision_analysis.py#L98) | `node_vision_analysis` (graph.py:247) | `call_gemini_vision` | `VisionAnalysisOutput` |
| 3 | [`agents/fraud_review.py:44`](../agent_core/agents/fraud_review.py#L44) | `node_fraud_review` (graph.py:377) | `call_gemini_text` | `FraudReviewOutput` |
| 4 | [`agents/decision.py:49`](../agent_core/agents/decision.py#L49) | `node_decision` (graph.py:414) | `call_gemini_text` | `DecisionOutput` |

`agents/vision_analysis.py:117` is a fifth call site but it is the opt-in text-only degraded
path, off by default, and it is deleted by this change.

**One correction to your list:** there is no separate *image quality* LLM call in the current
code. Image quality became deterministic in Phase 0.5 —
[`agents/image_validator.py`](../agent_core/agents/image_validator.py) does decode, existence,
resolution and format checks in pure Python with zero model calls. Your four are really:
claim understanding, vision, **fraud**, **decision**. That is convenient: fraud and decision
are the two you want moved to Python anyway, so collapsing to one perception call removes
*three* model calls, not two.

Per-claim today: **4 requests. 44 claims = 176 requests. Against a budget of 20.**

---

## 3. Proposed design

```
claims.csv (44)
      ↓
  preflight        deterministic: decode, verify, pHash, blur/exposure, downscale for upload
      ↓            claims with no usable image never reach the model
 batch scheduler   adaptive: image-count budget + RPD budget + checkpoint state
      ↓
 ONE multimodal request per batch   ← gemini-3.6-flash, response_schema=BatchPerceptionOutput
      ↓
 per-claim structured evidence      ← keyed by claim_id, validated, cross-checked
      ↓
 deterministic Python rule engine   ← alignment → fraud → confidence → decision → rule_ids
      ↓
 persist + checkpoint               ← resumable across quota-reset days
```

### 3.1 Request budget

| | requests | of 20 RPD |
|---|---:|---:|
| 3 claims/batch (your proposal) | **15** | 75% |
| 4 claims/batch | 11 | 55% |
| 5 claims/batch | 9 | 45% |

**I recommend keeping your 3.** Quota is not scarce at 15/20, but *accuracy* is: the real
risk in batching is cross-claim contamination, and smaller batches contain that risk. Buying
quota headroom we do not need by spending accuracy we do need is the wrong trade. The
fallback ladder (§1.4) covers retries far better than a larger batch size would.

### 3.2 Adaptive sizing — driven by image count, not bytes

Since tokens scale with image *count* and not resolution (§1.2), the budget is per-image:

```yaml
batching:
  max_claims_per_request: 3
  max_images_per_request: 9      # ~10K tokens on 3.6-flash, 4% of TPM
  max_images_per_claim: 6        # excess dropped by blur score, lowest first
  # A claim whose own image count exceeds max_images_per_request goes alone.
```

Rules: accumulate claims while `claims ≤ 3` **and** `images ≤ 9`. A claim with 7+ images
becomes its own batch. This is the "very large claim → 1 claim/request" case, expressed as an
invariant rather than a heuristic.

### 3.3 Claim isolation

The genuine risk of this design, and the one that needs defending in depth:

1. **Structural delimiting.** Each claim is fenced in the request:
   `=== CLAIM CLM-003 BEGIN ===` … `=== CLAIM CLM-003 END ===`, with every image immediately
   preceded by a text part naming its owner: `[CLM-003 image img_2]`.
2. **Explicit instruction**, as you specified: *"Analyze each claim independently. Never use
   an image or evidence belonging to another claim. Every observation must be associated with
   exactly one claim_id."*
3. **Schema-level binding.** The response is `list[ClaimPerception]`, each carrying its own
   `claim_id`; `supporting_image_ids` are scoped per claim.
4. **Post-hoc validation, which is the part that actually protects us.** After parsing:
   every requested `claim_id` present exactly once; no unexpected ids; every
   `supporting_image_id` within that claim's own image count. Any violation → the batch is
   **not** trusted. It is re-run at batch size 1 if quota allows, else those claims are
   checkpointed as unprocessed. We never accept a possibly-contaminated result.
5. **Isolation regression test.** A fixture batch pairing an obviously-damaged car with an
   obviously-undamaged one; the test fails if findings cross over. This is the check that
   tells us whether batch size 3 is actually safe, and it is how we would justify raising it.

### 3.4 The LLM returns evidence, not verdicts

```python
class ClaimPerception(BaseModel):
    claim_id: str
    image_quality: ImageQuality          # overall, score, issues[]
    claim_understanding: ClaimIntent     # claimed_part, claimed_issue, claimed_severity
    damage_analysis: DamageAnalysis      # damage_detected, damaged_parts[{part,severity,...}]
    claimed_part_visible: bool           # absence of evidence, kept distinct
    supporting_image_ids: list[str]      # 1-based, scoped to THIS claim
    evidence: list[str]
    uncertainties: list[str]

class BatchPerceptionOutput(BaseModel):
    results: list[ClaimPerception]
```

Note `alignment` is **absent** from the model's output, deliberately. Your example schema
includes it, but `part_match` / `severity_delta` are a comparison between two fields the model
has already reported — computing them in Python makes them reproducible, testable, and free.
Asking the model to do arithmetic it can get wrong, when we hold both operands, adds risk for
nothing. Everything else in your example schema is preserved.

Then, in pure Python: `alignment` → `fraud` → `confidence` → `decision`, each rule carrying a
`rule_id` that lands in the justification. No LLM involvement in any verdict.

### 3.5 Quota governor and failure taxonomy

The Phase 0.5 governor already tracks RPM/TPM/RPD per model and refuses rather than blocking
on daily exhaustion. Extensions needed:

| Failure | Classification | Action |
|---|---|---|
| 429 with `...PerMinute...` quota id | transient RPM | exponential backoff + jitter, retry |
| 429 with `...PerDay...` quota id | **RPD exhausted** | **stop this model.** Try next rung of the ladder; if none, checkpoint and exit cleanly |
| 500/502/503/504 | transient server | backoff, retry (bounded) |
| 400/401/403 | our bug | fail fast, no retry |
| Schema validation failure | bad batch | re-run at size 1 if budget allows, else checkpoint |

The RPM-vs-RPD distinction is the one that matters, and it is available in the error body:
`quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier` vs
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Phase 0.5 currently treats every 429
alike and burns up to 4 attempts on a daily exhaustion that cannot possibly succeed —
**four wasted requests against a 20-request budget.** Fixing that is worth more than any
batching gain.

Daily counters persist to disk (`.aurelix/quota_state.json`, keyed by model and UTC date), so
a restart does not forget what today already spent.

### 3.6 Checkpointing

SQLite at `.aurelix/checkpoint.db`, one row per claim, persisting exactly what you listed:
`claim_id`, `batch_id`, `model`, raw structured result, normalised result, fraud score,
confidence, decision, `rule_ids`, timestamp, status.

`status ∈ {pending, in_flight, done, failed, quota_deferred}`. On start, load `done` and skip
them. Stopping after 12 requests resumes at claim 37 tomorrow, not claim 1. Batches are
committed atomically — a partially-parsed batch commits nothing.

---

## 4. Minimal change set

Preserving existing business logic, schemas, and the frozen `output.csv` contract.

### New (5 files)

| File | Purpose |
|---|---|
| `agent_core/services/batch_scheduler.py` | Adaptive batching under image + RPD budgets |
| `agent_core/services/checkpoint.py` | SQLite resumable store |
| `agent_core/agents/perception.py` | The single batched multimodal call |
| `agent_core/agents/alignment.py` | Deterministic claimed-vs-observed comparison |
| `agent_core/decision_rules.py` + `config/decision_rules.yaml` | Ordered rule engine emitting `rule_id`s |

### Modified (6 files)

| File | Change |
|---|---|
| `services/gemini_client.py` | Add `call_gemini_batch()`; split 429 into RPM vs RPD; persist quota counters; model fallback ladder |
| `services/config.py` + `config/limits.yaml` | `gemini-3.6-flash` primary, batching block, fallback chain |
| `schemas/models.py` | Add `ClaimPerception`, `BatchPerceptionOutput`, `AlignmentResult`. **Keep every existing schema** — perception results are adapted into `VisionAnalysisOutput` / `ClaimIngestionOutput` so `output_mapper.py` and the contract are untouched |
| `orchestrator/graph.py` | Per-claim graph keeps its shape but starts from injected perception rather than calling the model. `node_fraud_review` and `node_decision` swap their LLM call for the rule engine |
| `prompts/templates.py` | New `BATCH_PERCEPTION_PROMPT` with fencing and isolation instruction |
| `main.py` | Two-pass: preflight+schedule+batch-infer, then per-claim deterministic graph |

### Deleted

`agents/vision_analysis.py:117` text-only path, and the LLM bodies of `fraud_review.py` /
`decision.py` (the modules stay, now deterministic).

**Unchanged:** `schemas/contract.py`, `output_mapper.py`, `evaluation/evaluate.py`,
`agents/user_risk.py`, `agents/policy_verification.py`, `agents/image_validator.py`, and all
74 existing tests must still pass.

---

## 5. Net effect

| | before | after |
|---|---:|---:|
| Requests for 44 claims | 176 | **15** |
| Fits in 20 RPD | no | **yes, 25% margin** |
| Daily capacity | 5 claims | **~58 claims** (one model) / ~176 (ladder) |
| LLM verdicts | fraud + decision | **none — Python only** |
| Resumable | no | yes |
| Billing | — | **none** |

Latency per claim rises (a 3-claim batch takes longer than a 1-claim request) while latency
per *batch run* falls sharply. That is the correct trade under your stated ordering:
correctness, isolation, determinism, free-tier fit, reproducibility, then latency.

---

## 6. Two things worth deciding before I build

1. **`batchGenerateContent` is supported by `gemini-3.6-flash`.** The asynchronous Batch API
   typically carries a *separate, larger* quota than interactive `generateContent`. If that
   holds on free tier it could make request budget a non-issue entirely. It returns results
   asynchronously (minutes to hours), which suits an offline 44-claim benchmark fine. I did
   not test it — probing costs quota and I did not want to spend your remaining 13 requests
   without asking. **Worth one experiment?**

2. **Batch size 3 is my recommendation, not a measurement.** The isolation test in §3.3 is
   what will tell us whether 3 is safe or whether it should be 2. I would build the scheduler
   to take the number from config, run the isolation fixture, and let the result decide.

And still open from before: **the 44 real claim images.** Everything above assumes they
arrive. Without them the pipeline correctly emits 44 × `not_enough_information`, and no
amount of batching changes that.
