# Phase 4.2 — Migrating the web platform onto the batched pipeline

`platform_backend` and `frontend` were the last consumers of the superseded ten-node graph.
Three phases of accuracy work had never reached a user through them. They now run the same
code path the benchmark measures.

**Cost: 1 Gemini request** (the first real end-to-end call the API server has ever made).

---

## 1. What changed

| file | change |
|---|---|
| `agent_core/service.py` | **new** — `analyse_claim` / `analyse_claim_events`, the single-claim public entry point |
| `agent_core/__init__.py` | exports `analyse_claim`; **`process_claim` removed** |
| `agent_core/run_pipeline.py` | `judge` / `to_output_row` moved into `service.py`; imports them |
| `agent_core/main.py` | rewritten as a thin front for the batched runner |
| `platform_backend/services/claim_service.py` | rewritten against `analyse_claim_events` |
| `platform_backend/api/routes.py` | dropped the `process_claim` import |
| `platform_backend/config.py` | **bug fix** — `load_dotenv()` (see §3) |
| `frontend/.../SubmitClaimTab.tsx` | stage list matches `PIPELINE_STAGES` |
| `frontend/.../LiveInvestigationViewer.tsx` | new graph; `skipped` and `failed` node states |

### The shape of the change

```
before   ingest → preflight → [vision | policy | similar | user_risk] → fraud → decision
         4 LLM calls per claim; the model produced the fraud score and the verdict

after    preflight → perception → [policy | user_risk | alignment] → decision
         1 LLM call per claim; everything after it is deterministic Python
```

Two decisions worth stating:

- **A batch of one is still a batch.** The web path calls `run_batch_perception` with a
  single claim rather than getting its own leaner request builder. The alternative is a
  second inference path that quietly drifts away from the one the benchmark measures —
  which is the exact situation this phase existed to end.
- **One code path, two interfaces.** `analyse_claim` is defined in terms of
  `analyse_claim_events` rather than repeating the sequence. This is not tidiness: the old
  backend kept its own copy of the graph's routing logic to drive the progress stream, and
  the copy had already drifted out of sync with the real router.

---

## 2. Contract changes — what a consumer will notice

**Unchanged:** every route and method (`POST /claims/submit`, `/claims/submit-multimodal`,
`/claims/submit-multimodal-stream`, `GET /claims`, `/claims/{id}`, `/queue`,
`POST /queue/{id}/verdict`, `GET /analytics`), every response model, the SSE envelope
(`data: {"stage", "status", "timestamp"}` then `{"stage": "done", "claim": {...}}`), the
database schema, and the frozen `output.csv` contract.

**Changed, and why:**

| what | before | after | why |
|---|---|---|---|
| SSE stage names | `image_validator`, `claim_ingestion`, `vision_analysis`, `policy_verification`, `similar_claims`, `user_risk`, `fraud_review`, `decision` | `preflight`, `perception`, `policy_verification`, `user_risk`, `alignment`, `decision` | The old names denote nodes that no longer exist. `claim_ingestion`, `vision_analysis` and `fraud_review` were three separate LLM calls now folded into `perception`; `decision` is now arithmetic. Naming them honestly is the point of the progress view. |
| SSE `status` values | `running`, `complete` | adds `skipped`, `failed` | A claim with no usable image never makes a request. That is the biggest quota saver in the system and the UI should say so rather than showing a completed model call that never happened. |
| `impact_direction` | free text from the old vision agent | always `null` | **No source in the new pipeline.** These were prose fields on the old unstructured vision response and are not in the structured perception schema. Column and API field retained at their defaults so no migration is needed and no consumer breaks — but they are dead, and either want a schema addition or a removal. Flagging rather than silently inventing values. |
| `drivable_status` | free text from the old vision agent | always `true` (the column default) | as above |
| `audit_logs[].agent_name` | old node names | `preflight`, `perception`, `policy_verification`, `user_risk`, `alignment`, `decision` | follows the stage rename |
| `python -m agent_core.main` flags | `--limit`, `--skip-validation-run`, `--allow-text-only` | `--claims`, `--image-root`, `--dry-run`, `--fresh` | The old flags belonged to a per-claim loop. Batching, checkpointing and resumption need a different set; `run_pipeline` has the full list. |

**Retained deliberately:** `policy_verification` and `user_risk` were always deterministic
CSV/history lookups, never LLM calls. They survive untouched and still populate
`policy_status`, `policy_reason`, `user_risk_score` and `risk_level`.

`similar_claims` (TF-IDF retrieval) is **not** wired into the new path. It fed the old
fraud agent's prose reasoning, which no longer exists; the deterministic fraud score has no
input for it yet. Phase 3 (task 4.4) replaces that layer wholesale, and re-attaching the
hand-rolled TF-IDF store first would be work thrown away.

---

## 3. The bug that only a running server could find

The Phase 2/4 report noted `platform_backend` "was edited but never exercised — no server
was started." Starting one found this on the very first request:

```
[Gemini] gemini-3.6-flash unavailable (... GEMINI_API_KEY is not set ...); advancing to next model
[Gemini] gemini-3.5-flash unavailable (... GEMINI_API_KEY is not set ...); advancing to next model
[Gemini] gemini-2.5-flash unavailable (... GEMINI_API_KEY is not set ...); advancing to next model
```

`platform_backend` never called `load_dotenv()`. `Settings` declares `env_file = ".env"`,
which populates the `Settings` object — but `agent_core` reads `GEMINI_API_KEY` from
`os.environ`, which nothing ever wrote to. The CLI always called `load_dotenv()`; the web
platform never did. **The API server could never have made a single successful LLM call.**

Two things worth saying about it. First, it is exactly the class of defect that survives
any amount of code review and dies the moment something is actually run. Second, **it
failed correctly**: the response was `not_enough_information` with
`R002_perception_unavailable` and the real error in the audit log, not a fabricated verdict.
The no-fabrication rule held under a failure nobody had anticipated.

---

## 4. What I verified, with output

The server was started and driven for real. Three requests, one of which reached Gemini.

**Endpoints:**

```
$ curl -s http://127.0.0.1:8078/
{"message":"AURELIX Claims Intelligence API v2 is online"}

$ curl -s http://127.0.0.1:8078/queue          -> 4 claims awaiting review
$ curl -s http://127.0.0.1:8078/analytics      -> {'total_claims': 18, 'supported_claims': 14,
                                                   'contradicted_claims': 1, 'not_enough_info_claims': 3,
                                                   'manual_review_claims': 5, 'average_confidence': 76.0}
$ curl -s "http://127.0.0.1:8078/claims?limit=3" -> [(18,'contradicted'), (17,'not_enough_information'), (16,'not_enough_information')]
```

**Zero-cost path — no usable image, so no request is made:**

```
$ curl -X POST /claims/submit -d '{"image_paths":"images/does_not_exist.jpg", ...}'
claim_status              not_enough_information
justification             No usable image evidence was submitted, so no visual finding
                          could be made. [R001_no_usable_image]
confidence_score          20
escalation_reason         confidence 20 below 70; verdict 'not_enough_information' always requires review

quota before: gemini-3.6-flash 17/20
quota after : gemini-3.6-flash 17/20      <- unchanged, no call made
```

**The real multimodal path — the adversarial severity-inflation case, on a real
photograph, through the web platform for the first time:**

```
$ curl -N -X POST /claims/submit-multimodal-stream \
    -F 'user_claim=The front bumper is completely destroyed and needs a full replacement.' \
    -F 'files=@tests/fixtures/images/car_damage.jpg'

data: {"stage": "preflight",           "status": "running"}
data: {"stage": "preflight",           "status": "complete"}
data: {"stage": "perception",          "status": "running"}
data: {"stage": "perception",          "status": "complete"}     <- 13.8s, one request
data: {"stage": "policy_verification", "status": "complete"}
data: {"stage": "user_risk",           "status": "complete"}
data: {"stage": "alignment",           "status": "complete"}
data: {"stage": "decision",            "status": "complete"}
data: {"stage": "done", "claim": {...}}
```

Persisted result:

```
claim_status                   contradicted
claim_status_justification     Damage is present on the claimed part but is materially less
                               severe than described. Evidence: img_1. [R042_severity_inflation]
object_part                    front_bumper
issue_type                     dent
severity                       medium
confidence_score               83
fraud_score                    30
risk_flags                     claim_mismatch;manual_review_required
audit stages                   preflight, perception, policy_verification, user_risk, alignment, decision
```

A real photograph of moderate bumper damage, a claim of total loss, and a `contradicted`
verdict naming the rule that produced it — end to end through the API, with a full audit
trail.

**Static checks:**

```
$ ./venv/bin/python -m pytest
159 passed in 0.62s

$ cd frontend && npx tsc --noEmit
(exit 0)

$ ./venv/bin/python -m agent_core.main --dry-run
=== AURELIX agent-core CLI (batched multimodal pipeline) ===
Plan: 0 claims / 0 images -> 0 request(s)
```

Frontend is Next 16.2.12 / React 19.2.4; the changed files are plain client components and
touch no framework API surface.

---

## 5. What I could not verify

- **The frontend was not rendered against a live backend.** It typechecks and the stage
  keys match `PIPELINE_STAGES` exactly, but no browser session drove the SSE stream. The
  progress graph is verified by construction, not by observation.
- **Concurrency.** One request at a time. The RPM governor is shared process-wide, but two
  simultaneous submissions were not tried, and at 5 RPM free tier the second would queue.
  Phase 5's async job contract is where this belongs.
- **`/claims/submit` caching.** `get_cached_result` short-circuits on `(user_id,
  image_paths)`, and for the multimodal path `image_paths` is synthesised from *filenames*
  — so two different photographs uploaded under the same filename by the same user would
  collide. Pre-existing, untouched, and now written down.
- **`impact_direction` / `drivable_status` consumers.** I did not audit the frontend for
  components that display them. They are `null` / `true` rather than absent, so anything
  reading them still gets a value.

---

## 6. Risks and tech debt introduced

- **Two dead fields** (`impact_direction`, `drivable_status`) now have no producer. Either
  add them to the perception schema or drop the columns; leaving them is the worst option
  long-term.
- **`similar_claims` is disconnected.** Retrieval no longer influences any verdict. That is
  a real reduction in inputs to the fraud score until 4.4 lands, and it is the immediate
  next task.
- **The old graph and its four LLM agents still exist on disk**, unreachable from
  `agent_core`'s exports but still importable by path. Task 4.3 is the guardrail that makes
  the unreachability enforced rather than assumed.
- **`analyse_claim` is synchronous** and blocks for the whole perception call (~14s
  observed). Acceptable for the SSE stream, wrong for `POST /claims/submit`, which holds a
  worker for the duration. Phase 5's 202-plus-poll contract fixes it.
- **`platform_backend/main.py` still uses `@app.on_event("startup")`**, deprecated in
  current FastAPI in favour of lifespan handlers. Untouched here; worth folding into Phase 5.

---

## 7. Recommended next

**4.3** immediately: the guardrail tests. The migration is only durable if a future change
cannot quietly reintroduce the four-call path, and right now that guarantee rests on an
export list rather than on a test.
