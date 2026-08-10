# Phase 6 — End to end, and deployable

The pipeline was correct and the platform was not shippable. A description and a photograph
went in one end, a real verdict came out the other, and almost nothing in between survived
contact with a second machine: the frontend called `127.0.0.1`, the evidence a verdict
rested on 404'd, and the submission wizard silently ran an analysis from a form the user had
never been shown.

**Cost: 3 Gemini requests** (two before the Pacific-midnight reset, one after).

| | before | after |
|---|---|---|
| Frontend API address | hardcoded `127.0.0.1:8000` | `NEXT_PUBLIC_API_URL` |
| Uploaded photographs | decoded, analysed, discarded | persisted and served |
| Evidence on the review screen | 404 on every image | renders |
| Upload caps | none | 6 files, 8 MB each, format sniffed |
| CORS | `*` **and** credentials — rejected by browsers | two coherent modes |
| Submission wizard | advanced invisibly; step 1 forever | works |
| Dashboard KPIs | four string literals | computed from `/analytics` |
| Claim timestamps | naive, read as local time | offset-qualified UTC |
| Long model call over SSE | silent for up to 185s | keepalive every 15s |
| Tests | 249 | **254** |

---

## 1. What changed

| file | change |
|---|---|
| `platform_backend/services/uploads.py` | **new** — the single upload edge: caps, sniffing, generated names, persistence |
| `platform_backend/main.py` | env-driven CORS, `/health`, `/ready`, `/uploads/{name}` |
| `platform_backend/config.py` | `CORS_ORIGINS`, `UPLOAD_DIR`, `MAX_UPLOAD_*` |
| `platform_backend/api/routes.py` | both multipart routes go through `read_uploads` |
| `platform_backend/api/v1.py` | same edge; SSE keepalive; UTC job timestamps |
| `platform_backend/services/claim_service.py` | `utc_iso`; analysis on a worker thread so the stream can breathe |
| `platform_backend/models/schemas.py` | `UTCTimestamps` serializer |
| `frontend/lib/api.ts` | `API_URL` from env, `assetUrl`, diagnosable errors, comment-tolerant SSE |
| `frontend/components/dashboard/SubmitClaimTab.tsx` | wizard fixed; reset; hand-off to the full report |
| `frontend/components/dashboard/SystemHealth.tsx` | **new** — header strip backed by `/ready` |
| `frontend/components/dashboard/HomeDashboard.tsx` | real KPIs, real relative times, rows open a claim |
| `frontend/components/dashboard/ReviewQueueTab.tsx` | real age; "open full investigation" |
| `frontend/components/dashboard/ClaimReviewTab.tsx` | evidence via `assetUrl` |
| `frontend/app/page.tsx` | claim selection re-fetches detail |
| `requirements.txt`, `render.yaml`, `frontend/.env.example` | **new** — deployment |
| `docs/DEPLOYMENT.md` | **new** |
| `tests/test_uploads.py`, `tests/test_stream_keepalive.py` | **new** — 16 tests |

---

## 2. Four bugs worth describing

**The evidence could not be looked at.** `image_paths` recorded `uploads/<the client's
filename>` for a file that was never written anywhere. The review timeline rendered an
`<img>` for every one and got a 404, so the single artefact the whole verdict rests on was
the one thing a reviewer could not see. Uploads are now persisted under a generated name —
the client's filename never touches the filesystem, because a caller who controls the name
controls the path — and served from a route rather than a `StaticFiles` mount. That last
detail was not cosmetic: a mount binds its directory at import time, and anything that
relocates storage afterwards leaves it serving a path that no longer holds the files.

**The submission wizard advanced behind the user's back.** Its four panels were `&&`
conditionals inside an `AnimatePresence mode="wait"`, itself nested inside the page-level
`mode="wait"`. The outgoing panel's exit never completed, so the incoming one never mounted:
`step` climbed 1 → 2 → 3 → 4 with each press of Continue while the screen kept rendering
step 1, and the fourth press ran a real analysis — one of twenty daily requests — from a
form asking for a policyholder ID. Keying a single child by `step` fixed the first
transition and the deadlock moved to the second, so the exit animation is gone entirely. A
180ms cross-fade is not worth that.

**CORS was configured to fail.** `allow_origins=["*"]` with `allow_credentials=True` is
forbidden by the spec; the browser rejects the response and Starlette drops the wildcard.
The wildcard was reaching for permissiveness and achieving the opposite. There are now two
coherent modes, and the `*` one turns credentials off to stay legal.

**Timestamps were read in the wrong timezone.** Columns hold naive UTC so SQLite can compare
them, and `.isoformat()` on a naive value emits no offset — which ECMAScript reads as
*local* time. Every claim landed hours in the reader's future. The dashboard hid this by
printing the literal string "Just now" on every row, and the review queue by printing "2h".
Both now compute from an offset-qualified timestamp.

---

## 3. The one that only shows up in production

A claim takes ~9 seconds. Under per-minute rate-limit backoff near the daily cap, one
measured run took **185 seconds** — and for all of it the SSE stream sends nothing, because
the gap between `perception:running` and `perception:complete` *is* the model call. Every
reverse proxy closes a response that has gone quiet for its idle timeout, ~100s on Render.
The analysis would complete server-side, spend one of twenty daily requests, and be
delivered to nobody.

Both streaming endpoints now emit an SSE comment every 15 seconds. For the blocking route
that meant moving the pipeline onto a worker thread and draining a queue, because a
generator cannot emit while it is blocked. Database work deliberately stayed on the calling
thread: a Session is not thread-safe, and trading a visible timeout for an invisible
corruption is not a fix.

---

## 4. What I verified, with output

**The full suite.**

```
$ ./venv/bin/python -m pytest
254 passed in 4.50s
```

**The real pipeline, through the real client.** `frontend/lib/api.ts` compiled and driven
from Node against a running backend — the same multipart body and SSE reader the browser
uses:

```
  ok  - /ready -> {"database":"ok","gemini_key":"present","retrieval_index":"loaded"}
  ok  - all 7 stages streamed in 184.6s        <- under backoff; 8-9s with budget free
  ok  - verdict -> supported (confidence 81, fraud 10)
        The submitted images confirm the claimed damage on the claimed part. [R052_supported]
  ok  - audit trail -> preflight, duplicate_check, perception, policy_verification,
                       user_risk, alignment, decision
  ok  - created_at is offset-qualified: 2026-08-10T02:02:53.292164+00:00
  ok  - evidence served: /uploads/aced05269f...jpg -> image/jpeg, 138359 bytes
  ok  - getClaim(21) -> supported, 7 audit entries
  ok  - bad upload -> "'notes.txt' is not a readable image."
ALL CHECKS PASSED
```

**The browser, end to end.** Production build, four wizard steps, a photograph attached, and
the agents launched. A cat photograph submitted against a car claim:

```
VERDICT    Contradicted                                    Execution Time: 9.40s
           The submitted images show a different object from the one described in
           the claim. Claim is about a car but the images show a animal. The claimed
           part (front_bumper) is not visible. [R010_wrong_object]
Confidence 26%    Fraud 45/100    Risk LOW
ESCALATED  confidence 26 below 70; verdict 'contradicted' always requires review
claim #23
```

The review screen for an earlier claim renders the uploaded photograph, the per-agent
reasoning, and a correct local timestamp.

**CORS, both modes.** Explicit origin and the preview regex are echoed with
`allow-credentials: true`; a disallowed origin gets no `access-control-allow-origin` header,
which is what makes the browser block it.

---

## 5. What I could not verify

- **The deployed environments.** Render and Vercel both need an interactive login; neither
  CLI is installed here. `render.yaml`, `requirements.txt` and the env templates are written
  and the dependency set resolves, but no build has run on Render's image. `PYTHON_VERSION`
  is pinned to 3.13.4 while local development is on 3.14.2 — the binary dependencies are
  floored rather than pinned so pip resolves wheels for whichever interpreter runs, but that
  is reasoning, not a green build.
- **The keepalive against a real proxy.** Asserted by unit test against a stubbed slow
  pipeline. No proxy has been placed in front of the server.
- **Concurrency.** Nothing has driven more than one submission at a time.
- **The 185s path end to end in a browser.** Reproducing it means exhausting the daily
  budget again.

---

## 6. Risks and tech debt

- **Still no auth.** `user_id` is a form field. Anyone can submit as anyone and read any
  claim by id. Unchanged from Phase 5.1 and still the highest-priority remaining item —
  deploying makes it reachable from the internet rather than from localhost.
- **Uploads are served without authorisation.** Anyone holding the URL can fetch the image.
  The names are unguessable UUIDs, which is obscurity, not access control.
- **Ephemeral storage.** Claims and photographs do not survive a redeploy.
- **Two submission contracts** — the blocking one the UI uses and the v1 async one — still
  coexist. Intended for one migration step; it has now lasted two phases.
- **`PROMPT.md` remains in `.gitignore`**, added by something I did not do in an earlier
  session. Flagged rather than changed, per your standing instruction.

---

## 7. Recommended next

**Auth and RBAC**, before this is public. Everything else on the list is hardening something
that is wide open underneath, and deployment turns "wide open on localhost" into "wide open
on the internet".
