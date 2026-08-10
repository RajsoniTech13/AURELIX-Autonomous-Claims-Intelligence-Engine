# Phase 3 (remainder) — Three collections, index lifecycle, citable policy rules

Task 4.4 built the retrieval machinery and the image index. This completes the collection
side of Phase 3: all three collections, an index lifecycle, and the first place retrieval
changes what the system *says*.

**Cost: 0 Gemini requests.**

| | before | after |
|---|---:|---:|
| Collections | 1 (rebuilt per query) | **3, built offline, loaded once** |
| Policy failures cite a rule id | no | **yes** |
| Tests | 207 | **227** |
| Benchmark accuracy | 93.2% | **93.2%** (unchanged) |

---

## 1. What changed

| file | change |
|---|---|
| `agent_core/retrieval/collections.py` | **new** — three collections, manifest, upsert, staleness |
| `agent_core/data/fraud_patterns.yaml` | **new** — six-pattern curated playbook |
| `agent_core/tools/build_index.py` | builds all three; upserts by default |
| `agent_core/agents/policy_verification.py` | cites stable `rule_id`s |
| `agent_core/schemas/models.py` | `PolicyVerificationOutput.rule_ids` |
| `platform_backend/main.py` | loads the built index instead of re-indexing a CSV per boot |
| `agent_core/services/vector_store.py` | **deleted** |
| `agent_core/agents/similar_claims.py` | **deleted** |
| `tests/test_collections.py` | **new** — 20 tests |

---

## 2. The collection that changes behaviour

`policy_rules` is chunked **one document per requirement**, not one per object category:

```
EV-CAR-COUNT        Minimum number of photographs required for a car claim: 1.
EV-CAR-VISIBILITY   Parts that must be visible ...: front_bumper, rear_bumper, ...
EV-CAR-ANGLE        Acceptable viewing angles for car evidence: full_context, close_up.
EV-CAR-TYPE         Acceptable evidence types for a car claim: photo.
```

Twelve documents across three categories. The compliance check now cites them:

```
status   : WARNING
reason   : The claimed part 'spoiler' is not listed in visibility requirements for car
rule_ids : ['EV-CAR-VISIBILITY']
```

**"EV-CAR-VISIBILITY failed" is answerable to a claimant. "The car policy failed" is not.**
That is the whole reason for chunking at requirement granularity rather than storing one
blob per object.

Two properties are pinned by test:

- **Ids are stable against reordering.** They derive from the object category and the field
  name, never from row order, so shuffling the CSV cannot silently repoint every stored
  citation at a different requirement. The test reverses the file and asserts the id set is
  identical.
- **Every id the agent can emit resolves to a real document.** A citation that resolves to
  nothing looks like an audit trail and is not one, which is worse than not citing at all.

---

## 3. The other two collections

**`historical_claims`** indexes the narrative **plus what was actually observed**, read from
the stored perception already on disk. Indexing the claimant's words alone retrieves claims
that *sound* alike; adding the observed part, damage type and final verdict retrieves claims
that *turned out* alike — which is the question a reviewer is actually asking. Metadata
carries `object_category`, `observed_part`, `damage_type`, `severity`, `final_verdict`.

**`fraud_patterns`** is a six-entry curated playbook with stable `FP-…` ids, a
`reviewer_prompt` for each, and `related_rules` linking to the engine.

**It cannot move a verdict, by construction.** Nothing reads it into the fraud score. A
retrieved similarity is not evidence, and an outcome that cannot be traced to a rule id is
exactly what Phase 1 removed. What it provides is reviewer context: when a claim is
escalated, the queue can say which known pattern it resembles and what to check next —
including, in three of the six entries, an explicit warning that the pattern is more often
carelessness than fraud.

A test asserts every `related_rules` entry exists in `config/decision_rules.yaml`, so the
playbook cannot rot into referring to rules the engine no longer has.

---

## 4. Lifecycle

The manifest records `index_version` and a content **fingerprint per collection**:

```json
{"index_version": 1,
 "collections": {
   "historical_claims": {"count": 44, "fingerprint": "695a8837f1679d6a", ...},
   "policy_rules":      {"count": 12, "fingerprint": "5fe162e35ecfb907", ...},
   "fraud_patterns":    {"count":  6, "fingerprint": "575a3e66c92199f1", ...}}}
```

- **A stale index is worse than no index, because it answers confidently.** The fingerprint
  makes staleness detectable (`stale_collections()`), and the build reports which
  collections were rebuilt because their source changed.
- **A version mismatch raises rather than guesses.** An index written by a different builder
  may have a different document shape.
- **Builds upsert by default** (`--fresh` to start over), so a nightly run can add
  yesterday's claims without re-reading the whole history and a partial build cannot
  silently truncate a collection to whatever it happened to see.
- **Retrievers are built on first use and cached**, and an upsert invalidates the cache.
  Never per query — which is what the deleted store did.

---

## 5. What I verified, with output

```
$ ./venv/bin/python -m agent_core.tools.build_index
Image index       :  46 fingerprints (3 skipped on quality, 0 unreadable)
historical_claims :  44 documents  fingerprint 695a8837f1679d6a
policy_rules      :  12 documents  fingerprint 5fe162e35ecfb907
fraud_patterns    :   6 documents  fingerprint 575a3e66c92199f1
Manifest    : .aurelix/index/manifest.json  (index_version 1)
No API calls were made.
```

The API server loads it at startup — verified by starting one:

```
$ curl -s http://127.0.0.1:8079/
{"message":"AURELIX Claims Intelligence API v2 is online"}
[Retrieval] index loaded: {'historical_claims': 44, 'policy_rules': 12, 'fraud_patterns': 6}
```

Loading is **best-effort on purpose**: a missing or out-of-date index must not stop the API
accepting claims, because retrieval informs a reviewer rather than deciding anything. A
version mismatch logs and degrades to an empty bundle instead of refusing to boot.

```
$ ./venv/bin/python -m pytest
227 passed in 1.52s

$ ./venv/bin/python -m agent_core.evaluation.evaluate_synthetic
Scored 44/44  accuracy 93.2%  macro-F1 93.2%
```

---

## 6. What I could not verify

- **Retrieval still influences no verdict.** `historical_claims` and `fraud_patterns` are
  built, tested and queryable, but nothing consumes them: the deterministic fraud score has
  no input for retrieval agreement, and I did not add one. Wiring a similarity score into a
  verdict is a design decision with real risk (see §3) and it wants your call rather than
  mine. Only `policy_rules` currently changes output.
- **recall@5 is measured on 3–6 probes**, on a 44-document corpus. It is a smoke test, not
  a retrieval evaluation, and it is not comparable to the "documented improvement over the
  TF-IDF baseline" the original brief asked for — the baseline is deleted, and re-implementing
  it to benchmark against would be measuring a thing nobody will run.
- **The <150ms retrieval budget is untested.** Queries are sub-millisecond on 44 documents;
  that number says nothing about 44,000.
- **`fraud_patterns` content is my invention**, not a real fraud playbook. It is plausible
  and internally consistent; it is not domain-validated.

---

## 7. Risks and tech debt introduced

- **Two deleted modules had no replacement consumer.** `similar_claims.py` fed the old
  fraud agent's prose reasoning, which no longer exists. Removing it is correct, but it
  means retrieval-based fraud context is *absent* rather than *replaced* until something
  consumes the new collections.
- **`app.state.index` is loaded once at startup and never refreshed.** A rebuild requires a
  restart. Fine now, wrong when index builds are on a schedule.
- **The `dense` arm is still LSA**, not embeddings. Unchanged from 4.4 and unchanged for the
  same reason: embeddings spend request quota.
- **`agent_core/data/sample_claims.csv` is now unreferenced** by any code path.

---

## 8. Recommended next

**Phase 5** — the production hardening block: the 202-plus-poll async job contract (currently
`POST /claims/submit` blocks a worker for ~14s), SQLAlchemy 2.0 async + Alembic (the schema
is still `create_all`), auth and RBAC (there is none), upload hardening, and observability.
The single highest-value item is the async job contract, because the synchronous blocking
call is what will fall over first under any real load.
