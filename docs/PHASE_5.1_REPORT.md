# Phase 5.1 — Asynchronous claim submission

`POST /claims/submit` held a worker open for the whole of a model call — ~14 seconds
measured in 4.2. This replaces that with a job contract: 202, poll, stream.

**Cost: 0 Gemini requests.**

| | before | after |
|---|---|---|
| Submission | blocks ~14s | **202 immediately** |
| Concurrency limit | worker count | job pool (4), bounded by 5 RPM quota |
| Client timeout | loses paid-for work | job continues, result collected later |
| Retry safety | duplicate claim + duplicate request | **Idempotency-Key** |
| Paging | offset | **cursor** |
| Tests | 227 | **238** |

---

## 1. What changed

| file | change |
|---|---|
| `platform_backend/api/v1.py` | **new** — `POST /api/v1/claims`, `GET /jobs/{id}`, `/jobs/{id}/stream`, `/claims`, `/claims/{id}` |
| `platform_backend/services/jobs.py` | **new** — job lifecycle, pool executor, orphan reaping |
| `platform_backend/db/models.py` | `Job` table |
| `platform_backend/main.py` | v1 router, orphan reap at startup, drain at shutdown |
| `tests/test_job_api.py` | **new** — 11 tests |
| `tests/conftest.py` | image index isolated **per test** (§4) |

The unversioned blocking routes are untouched and still serve the current frontend.
Breaking a working UI to land a contract change is not an improvement; the migration path
is `submitClaimStream` → `POST /api/v1/claims` + `/jobs/{id}/stream`, which is a
frontend-only change once someone wants it.

---

## 2. Design decisions worth defending

**The executor is a bounded thread pool, and I am saying so rather than implying otherwise.**
The brief specified ARQ over Redis. There is no broker here and no budget to add one, and
writing code against a Redis that never runs would be worse than stating the limitation. So
what is built correctly is the **contract** — 202, a durable job row, poll and stream
endpoints — because that is the part clients depend on. Swapping `ThreadPoolExecutor` for an
ARQ worker changes `services/jobs.py` and nothing else.

Two consequences of a single-process pool, stated up front rather than discovered later:

- Jobs do not survive a restart. `reap_orphans()` marks them failed at startup, because a
  job stuck in `running` forever is worse than one that reports honestly it was interrupted —
  a client polls it indefinitely and no operator ever finds out.
- The pool is 4. That is not a CPU number: the real ceiling is 5 requests per minute of free
  quota, and a larger pool would only queue harder against the rate governor.

**The job row is the progress channel — no broker, deliberately.** Progress has to survive a
client reconnecting mid-analysis, which means it has to be durable, which means the database
is already the right place for it. The SSE endpoint reads the row and terminates on a
terminal status.

**Images are decoded at submission, not on the worker.** A malformed upload fails fast with a
400 the client can act on, instead of becoming a job that fails asynchronously for a reason
the submitter never sees.

**Idempotency is scoped per user.** A shared key across claimants would return one person's
claim to another. A replay returns **200**, not 202, because nothing new was accepted.

**Cursor pagination.** Offset paging re-scans skipped rows and silently skips or repeats
records when rows are inserted mid-page. For a review queue that means a claim nobody ever
sees.

---

## 3. Two bugs the tests found

**Progress was never persisted.** `_record` mutated the dicts already inside `job.progress`.
A plain JSON column has no mutation tracking: SQLAlchemy decides whether to emit an UPDATE
by diffing the attribute's old snapshot against the new value, and mutating the existing
dicts mutates the snapshot too — so `old == new` and the write was silently dropped. The job
completed correctly and reported **no progress at all**. Fixed by building fresh dicts.

**The test spy answered with a fixed `claim_id`.** The batch isolation check correctly
rejected it, which quietly turned every test using the spy into a test of
`BatchIsolationError` rather than of whatever it meant to cover. It now echoes the ids it was
actually asked about.

---

## 4. And one the *full suite* found

`test_polling_reaches_a_finished_claim` passed in isolation and failed in the suite. Two
tests generate a photograph from the same random seed, so they produce **byte-identical
images**; the session-scoped image index matched the second against the first as a reused
photograph and returned `contradicted` instead of `supported`.

The detector was right. The shared index was the bug. Index isolation moved from session
scope to **per test**, which removes the whole class of order-dependent flakiness — and is a
reminder that the image index is the first persistent, mutating store in this system.

---

## 5. What I verified, with output

Live against a running server, using a claim with no images so perception is skipped and no
quota is spent:

```
$ curl -i -X POST /api/v1/claims -H 'Idempotency-Key: demo-1' -F ...
HTTP/1.1 202 Accepted
location: /api/v1/jobs/10611e74-de81-43fc-a8b8-eecc7743c1af

$ curl -i -X POST /api/v1/claims -H 'Idempotency-Key: demo-1' ...   # same key
HTTP/1.1 200 OK                                                     # not 202

$ curl /api/v1/jobs/10611e74-...
status  : succeeded
claim_id: 19
progress: [('preflight','complete'), ('duplicate_check','complete'), ('perception','skipped'),
           ('policy_verification','complete'), ('user_risk','complete'),
           ('alignment','complete'), ('decision','complete')]

quota before: gemini-3.6-flash 18/20
quota after : gemini-3.6-flash 18/20      <- unchanged
```

```
$ ./venv/bin/python -m pytest
238 passed in 2.91s

$ ./venv/bin/python -m agent_core.evaluation.evaluate_synthetic
Scored 44/44  accuracy 93.2%  macro-F1 93.2%
```

---

## 6. What I could not verify

- **Concurrency under load.** No k6/Locust run; nothing has driven more than one submission
  at a time. The pool bound is asserted by construction, not by measurement.
- **SSE through a proxy.** `X-Accel-Buffering: no` and `Cache-Control: no-cache` are set
  because an intermediary that buffers the stream defeats the point of it, but no proxy was
  in front of the server to test against.
- **Idempotency under a race.** Two simultaneous submissions with the same key can both miss
  the lookup and create two jobs. A unique index on `(user_id, idempotency_key)` would close
  it; the column is indexed but not unique.
- **The stream timeout (300s)** was not exercised.

---

## 7. Risks and tech debt introduced

- **Two submission contracts now exist.** The unversioned blocking routes and the v1 async
  ones. That is intentional for one migration step and should not become permanent.
- **Still `create_all`, no Alembic.** The `jobs` table appeared by `create_all` on an
  existing SQLite file, which happens to work for a pure addition and will not for the first
  column change. Migrations are the next item.
- **No auth on any of this.** `user_id` is a form field, so anyone can submit as anyone and
  read any claim by id. That is unchanged from before, but the async contract makes it
  easier to enumerate jobs. It is the highest-priority remaining Phase 5 item.
- **Uploads are unbounded.** No size cap, no content-type sniffing beyond `Image.open`, no
  storage abstraction — images live only in memory for the life of the job and are never
  persisted, so `image_paths` records filenames that resolve to nothing.
- **`reap_orphans` fails *queued* jobs too.** Correct for a single process, wrong the moment
  a second one starts: it would fail jobs another worker is about to pick up.

---

## 8. Recommended next

**Auth and RBAC**, then Alembic. Auth is the larger risk — the API currently trusts a form
field for identity, and every other Phase 5 item is hardening something that is wide open
underneath.
