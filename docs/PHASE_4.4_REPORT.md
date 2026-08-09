# Phase 4.4 — Hybrid retrieval, and making `R030_duplicate_image_reuse` fire

`R030` has been in `config/decision_rules.yaml` since Phase 2 with nothing capable of
setting its condition. The strongest objective fraud signal in this domain — a photograph
already submitted under another claim — was declared and dead. It is alive.

**Cost: 0 Gemini requests.** Nothing in this phase calls a model.

| | before | after |
|---|---:|---:|
| Rules that can fire | 12 of 13 | **13 of 13** |
| Tests | 172 | **207** |
| Retrieval arms | 1 (TF-IDF, rebuilt per query) | **2 + RRF fusion** |
| Metadata filtering | none | **mandatory, pre-scoring** |
| Benchmark accuracy | 93.2% | **93.2%** (unchanged, as intended) |

---

## 1. What changed

| file | change |
|---|---|
| `agent_core/retrieval/hashing.py` | **new** — pHash (DCT) and dHash (gradient), numpy only |
| `agent_core/retrieval/image_index.py` | **new** — SQLite fingerprint store, exact + near tiers |
| `agent_core/retrieval/hybrid.py` | **new** — dense + BM25 + RRF + metadata filtering |
| `agent_core/tools/build_index.py` | **new** — offline index build |
| `agent_core/evaluation/evaluate_duplicates.py` | **new** — precision/recall harness |
| `config/retrieval.yaml` | **new** — thresholds, with the measurements behind them |
| `agent_core/service.py` | `duplicate_check` stage, before perception |
| `agent_core/run_pipeline.py` | `--duplicate-detection` (off by default — §4) |
| `agent_core/rules_engine.py` | `evidence_notes`, so a verdict can name the prior claim |
| `platform_backend/…/claim_service.py`, `frontend/…` | new stage in the audit trail and the UI |
| `tests/conftest.py`, `tests/test_retrieval.py` | **new** — index isolation, 35 tests |
| `agent_core/requirements.txt` | `+rank_bm25`, **`-langgraph`** |

---

## 2. Why hashes rather than embeddings

A cryptographic hash changes completely when one byte does, so re-saving a JPEG at a
different quality defeats it entirely — and re-saving is what happens to every photograph
that passes through a phone. A perceptual hash is computed from image structure, so it
survives re-encoding, resizing, brightness changes and light cropping.

**Two hashes, and both must agree.** pHash is a frequency-domain signature, dHash a gradient
one; they fail differently. An OR would inherit the worse failure mode of the two, and this
is a rule that accuses somebody of fraud, so the conjunction is deliberate.

**Two tiers, because they are not the same evidence.** An identical-pixels match is a fact
with no threshold attached. A perceptual match is a judgement, and it travels with its bit
distances so a reviewer can weigh it.

**What is stored is not the photograph** — two 64-bit hashes and a content hash. The index
can say "this image was submitted before, under claim X" while retaining nobody's photo.

The `content_hash` is taken over decoded **pixels**, not file bytes: re-saving an unmodified
image changes the container (different encoder, stripped EXIF, different quantisation
tables) while the photograph is the same one, and that case belongs in the exact tier rather
than degrading to a judgement call.

---

## 3. Where the thresholds come from

Measured before any threshold was written, on the **real photographs** in
`tests/fixtures/images` — the only corpus that can answer this question. Bit distance
between an image and a transformed copy of itself (pHash / dHash):

| | jpeg q55 | resize 50% | crop 4% | bright ±20% |
|---|---:|---:|---:|---:|
| `car_damage.jpg` | 0 / 0 | 0 / 0 | 10 / 5 | 2 / 0 |
| `cat.jpg` | 0 / 0 | 0 / 0 | 12 / 8 | 2 / 1 |

and between *different* photographs — the false-positive risk:

| pair | pHash | dHash |
|---|---:|---:|
| car_damage vs cat | 26 | 30 |
| car_damage vs blurred | 24 | 35 |
| **minimum over all genuine pairs** | **24** | **18** |

`pHash <= 12 AND dHash <= 10` therefore has roughly 2× headroom on both sides.

### The quality gate is a precondition, not a neighbour

One image breaks the pattern: `blurred.jpg` moves **22 pHash bits under nothing worse than a
JPEG re-encode**. A near-featureless image has DCT coefficients bunched around the median, so
trivial perturbations flip many bits. Indexing such an image manufactures false accusations.

It is excluded for free. `blurred.jpg` has a Laplacian variance of 0.6, and the Phase 4.1
gate already rates it `unusable`; only images the gate accepts are indexed. The offline
build shows this working on the synthetic set:

```
  skip SYN-031 img_1: quality unusable
  skip SYN-032 img_1: quality unusable
  skip SYN-033 img_1: quality unusable
Image index : 46 fingerprints (3 skipped on quality, 0 unreadable)
```

4.1 was built to fix `poor_image`. It turns out to be what makes 4.4 safe.

---

## 4. The finding: the synthetic set cannot measure this feature

```
$ ./venv/bin/python -m agent_core.evaluation.evaluate_duplicates

REAL PHOTOGRAPHS (quality-gated)          SYNTHETIC RENDERS (quality-gated)
  false positives : 0 of 1 pairs            false positives : 110 of 1035 pairs (10.6%)
  closest genuine pair: 30 bits             closest genuine pair: 0 bits
  recall          : 87.5%                   recall          : 83.4%
```

**110 false positives is the detector telling the truth about the corpus.** Every car case
in the synthetic set renders the same car template at the same angle, differing only by a
small damage mark. Two *different* claims therefore produce genuinely near-identical
photographs — `SYN-007_img_1` and `SYN-029_img_1` are **0 bits apart on both hashes**. No
threshold can separate them, because there is nothing to separate.

Consequences, stated plainly:

- **The 93.2% synthetic accuracy figure says nothing about duplicate detection.**
- Batch duplicate detection is **opt-in** (`--duplicate-detection`) and **off** for the
  synthetic benchmark. Enabling it there would measure the dataset rather than the system,
  and would silently corrupt the accuracy number. This is a statement about the corpus, not
  a weakening of the feature — the web platform runs it on by default.
- The real-photograph precision figure rests on **1 genuine pair**. Zero false positives out
  of one pair is not a strong claim and is not presented as one; see §7.

Recall misses `cropped 10%` on both corpora (26/16 bits — beyond the thresholds). That is
the intended trade: a threshold loose enough to catch a 10% crop is loose enough to start
accusing honest claimants, and a missed duplicate merely returns us to the verdict we would
have reached without the feature.

---

## 5. The hybrid retriever

Replaces `services/vector_store.py`, which rebuilt its entire vocabulary and IDF table
**inside every `search()` call** and had no metadata filtering at all — so scoring a car
claim happily returned laptop claims.

- **Sparse:** BM25 (`rank_bm25`).
- **Dense:** LSA — truncated SVD over TF-IDF, in numpy. It retrieves on term co-occurrence
  rather than exact overlap, which is what the dense arm is for, and it costs nothing.
  **It is not a transformer embedding and is not described as one.**
  `GeminiEmbeddingBackend` implements the same interface and deliberately raises
  `NotImplementedError`: generating embeddings spends request quota, which the brief forbids
  without approval. A test asserts it refuses rather than quietly starting to spend.
- **Fusion:** Reciprocal Rank Fusion. Chosen over a weighted score blend because cosine
  similarity and BM25 live on incomparable scales; blending needs a normalisation and a
  weight that must be re-fitted whenever the corpus changes and never is. RRF needs only
  ranks.
- **Metadata filtering is applied before scoring**, not as a post-filter. Post-filtering
  silently returns fewer than *k*, and does so worst exactly when the corpus is dominated by
  another category — the case the filter exists for.

`recall@5 = 6/6` on a labelled probe set of paraphrases (not substrings) — small, and
reported as such.

---

## 6. What I verified, with output

**R030 firing against the real 46-fingerprint index.** A claimant resubmits `SYN-008`'s
photograph under a new claim and a new user id, re-encoded at JPEG q45:

```
duplicate matches:
  img_1 matches img_1 of claim SYN-008 (claimant user_009) perceptually
  [pHash 0, dHash 3 bits apart].

WITHOUT the index, this claim scores : supported      (fraud 10, review False)
WITH the index                      : contradicted   (fraud 55, review True)

rule_ids     : ['R030_duplicate_image_reuse', 'FRAUD:duplicate_image_reuse']
risk_flags   : ['claim_mismatch', 'manual_review_required', 'possible_manipulation']
justification: An image in this claim was previously submitted under a different claim.
               img_1 matches img_1 of claim SYN-008 (claimant user_009) perceptually
               [pHash 0, dHash 3 bits apart]. Evidence: img_1. [R030_duplicate_image_reuse]
```

A claim that would have been **auto-approved** is now contradicted, flagged, and routed to a
human — with the prior claim named in the justification.

```
$ ./venv/bin/python -m agent_core.tools.build_index --fresh
Image index : 46 fingerprints (3 skipped on quality, 0 unreadable)  [46 total]
Text index  : 44 documents
No API calls were made.

$ ./venv/bin/python -m pytest
207 passed in 1.55s

$ ./venv/bin/python -m agent_core.run_pipeline
Quota after run: gemini-3.6-flash: 18/20      <- unchanged, zero requests
$ ./venv/bin/python -m agent_core.evaluation.evaluate_synthetic
Scored 44/44  accuracy 93.2%  macro-F1 93.2%

$ cd frontend && npx tsc --noEmit
(exit 0)
```

Ordering is asserted by test: `duplicate_check` runs **before** `perception`, so the query
sees the index as it was before this claim. A detected duplicate does **not** skip the model
call — the audit trail still needs to say what was in the photograph, and `R030` sits below
`R010_wrong_object` and `R003` in the rule order, all of which read perception.

---

## 7. What I could not verify

- **Precision on real photographs rests on one pair.** Two quality-passing real images exist
  in this repository. Zero false positives out of one pair is directionally right and
  statistically almost nothing. **These thresholds need re-deriving on a real corpus of
  hundreds of photographs before this rule is trusted to contradict a claim in production.**
- **No adversarial transformations were tested.** Rotation, horizontal flip, heavy crop,
  overlay and re-photographing a screen all defeat these hashes, and a claimant who knows
  the system is in place will reach for exactly those. This catches carelessness and
  opportunism, not a determined attacker.
- **Cross-claimant behaviour at scale.** The index holds 46 fingerprints. Collision
  probability grows with corpus size, and 46 says nothing about 46,000.
- **The hybrid retriever is not wired into any verdict.** It is built, tested and measured,
  but nothing consumes its results yet: the deterministic fraud score has no input for
  retrieval agreement. That is Phase 3's remaining work (three collections, index
  lifecycle), not an oversight — but retrieval currently influences no outcome.
- **recall@5 = 6/6 on 6 probes** is a smoke test, not a retrieval evaluation.

---

## 8. Risks and tech debt introduced

- **The index is a persistent, mutating store** — the first in this system where running the
  suite could change production behaviour. `tests/conftest.py` isolates it per session, and
  that isolation must not be removed.
- **Duplicate lookup is a linear scan** with a popcount per candidate. Microseconds at
  today's size, and it degrades linearly. Production scale wants a BK-tree or multi-index
  LSH over the hash space; the interface does not change when that arrives.
- **No index lifecycle.** No versioning, no incremental rebuild policy, no eviction. Phase 3
  proper covers this.
- **`services/vector_store.py` is still present** and still called by
  `platform_backend/main.py` at startup, feeding nothing. It should be deleted when the
  hybrid retriever is actually consumed.
- **`langgraph` removed from requirements.** Nothing imports it since 4.3. If a real fan-out
  returns, the measured finding that LangGraph 1.2.6 genuinely parallelises still stands.
- **Near-duplicate detection off for the synthetic benchmark** is correct today and is a
  trap tomorrow: anyone who assumes the benchmark exercises this feature will be wrong. It
  is documented in the flag's help text, in the runner's source, and here.

---

## 9. Recommended next

Section 4 is complete. The natural next step is **Phase 3's remainder** — the three-collection
index (`historical_claims`, `policy_rules`, `fraud_patterns`), index lifecycle, and recall@5
on a real probe set — which is also what connects the retriever built here to an actual
verdict. `policy_rules` is the highest-value of the three: it would let the compliance check
cite retrieved `rule_id`s instead of the hardcoded CSV lookup it uses now.
