# Deploying AURELIX

Backend on **Render**, frontend on **Vercel**, both free tier. Roughly fifteen minutes,
most of it waiting for the first build.

The two halves are deployed in a specific order because each needs the other's URL, and
the frontend's copy is baked in at build time:

```
1. Render  → get https://<api>.onrender.com
2. Vercel  → set NEXT_PUBLIC_API_URL to that, deploy, get https://<app>.vercel.app
3. Render  → set CORS_ORIGINS to that, redeploy
```

Step 3 is not optional. Until it runs, the browser refuses every cross-origin call and the
UI reports the API as offline.

---

## 1. Backend → Render

Push the repository to GitHub, then in the Render dashboard: **New → Blueprint**, point it
at the repo. [`render.yaml`](../render.yaml) supplies everything except the secrets, which
Render prompts for because they are marked `sync: false`.

| variable | value |
|---|---|
| `GEMINI_API_KEY` | from https://aistudio.google.com/apikey |
| `CORS_ORIGINS` | `*` for now — tightened in step 3 |

What the blueprint does that is worth knowing:

- **Builds the retrieval index during the build** (`python -m agent_core.tools.build_index`).
  The index lives under `.aurelix/`, which is gitignored local run state, so it does not
  arrive with the checkout. It costs no API requests. Without it the API still starts and
  still decides claims correctly — retrieval informs a reviewer, it does not decide
  anything — but `/ready` reports `retrieval_index: empty`.
- **One worker.** The streaming route holds a worker for the length of the model call, and
  a second worker on 0.1 CPU would contend rather than help.
- **Health check on `/health`**, which deliberately does no I/O. A health check that touches
  the database reports the database's problems as the process's, and the platform then
  restarts a container that was never the problem.

Verify:

```bash
curl https://<api>.onrender.com/health
curl https://<api>.onrender.com/ready
```

`/ready` should report `database: ok` and `gemini_key: present`. A missing key does **not**
make the service unready — the pipeline degrades to an honest `not_enough_information`
rather than inventing a verdict — so check it explicitly rather than assuming.

## 2. Frontend → Vercel

**Add New → Project**, import the repo, and set **Root Directory** to `frontend`. Vercel
detects Next.js on its own; the defaults are correct.

One environment variable:

| variable | value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<api>.onrender.com` — no trailing slash |

`NEXT_PUBLIC_` is required: these calls run in the browser, and Next.js strips anything
without that prefix out of the client bundle. It is also **inlined at build time**, so
changing it later needs a redeploy, not a restart.

## 3. Back to Render — close the CORS hole

Set `CORS_ORIGINS` to the Vercel production URL and redeploy:

```
CORS_ORIGINS=https://<app>.vercel.app
```

The two modes are genuinely different, not just stricter:

- `*` — any origin, and credentials are **off**. The spec forbids a wildcard
  `Access-Control-Allow-Origin` on a credentialed request, so leaving both on is not lax,
  it is broken: the browser rejects the response.
- an explicit list — those origins, credentials allowed.

`CORS_ORIGIN_REGEX` is already set to `https://.*\.vercel\.app` in the blueprint, which
admits preview deployments. Their hostname changes on every push, so they cannot be
enumerated in advance. Drop it if you do not want previews reaching production data.

---

## Free-tier behaviour to expect

**The API sleeps.** Render free instances spin down after ~15 minutes idle and take ~50s to
wake. The first request after a quiet period looks like a hang. The frontend says so in its
error text instead of showing "Failed to fetch".

**Storage is ephemeral.** SQLite and uploaded photographs live on the container's disk and
are wiped by the next deploy. For persistence set `DATABASE_URL` to a Postgres URL and
replace `save_image()` in `platform_backend/services/uploads.py` — nothing else knows where
bytes live.

**Twenty model requests per day**, per project per model, resetting at **midnight Pacific**
(not UTC). Rotating keys does not reset it. Past the cap the pipeline returns a real
`not_enough_information` with the cause attached; it never fabricates a verdict. Near the
cap, per-minute backoff can stretch a 9-second analysis to three minutes — which is why
both streaming endpoints emit an SSE keepalive every 15 seconds, without which Render's
proxy would close a connection that has gone quiet.

---

## Running locally

```bash
cp .env.example .env                 # add GEMINI_API_KEY
python -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python -m agent_core.tools.build_index
./venv/bin/python -m uvicorn platform_backend.main:app --reload --port 8000
```

```bash
cd frontend
cp .env.example .env.local           # defaults to http://127.0.0.1:8000
npm install && npm run dev
```

```bash
./venv/bin/python -m pytest          # 254 tests, hermetic, no live API calls
```

---

## Environment reference

**Backend**

| variable | default | notes |
|---|---|---|
| `GEMINI_API_KEY` | — | required for perception; without it every claim returns `not_enough_information` |
| `CORS_ORIGINS` | `*` | comma-separated; `*` disables credentials (see above) |
| `CORS_ORIGIN_REGEX` | — | for Vercel preview hostnames |
| `DATABASE_URL` | `sqlite:///./aurelix.db` | any SQLAlchemy URL |
| `UPLOAD_DIR` | `<repo>/var/uploads` | where claim photographs are written |
| `MAX_UPLOAD_BYTES` | `8388608` | per file |
| `MAX_UPLOAD_FILES` | `6` | per claim |

**Frontend**

| variable | default | notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | build-time, no trailing slash |
