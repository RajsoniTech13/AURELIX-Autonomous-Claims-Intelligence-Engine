import logging
import os
import sys

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Ensure project root is in path so we can import platform_backend and agent_core
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from platform_backend.config import settings
from platform_backend.db.session import init_db
from platform_backend.api.auth import router as auth_router
from platform_backend.api.routes import router
from platform_backend.api.v1 import router as v1_router
from platform_backend.security import verify_asset
from platform_backend.services.uploads import UPLOAD_URL_PREFIX, upload_dir

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")
logger = logging.getLogger(__name__)


# Unhandled errors become a JSON 500 *inside* the CORS layer.
#
# Starlette turns an uncaught exception into a plain-text 500 in its outermost middleware,
# outside CORS, so that response carries no `Access-Control-Allow-Origin`. A browser then
# refuses to show the page the response and reports only "Failed to fetch" — a
# server bug disguised as a network outage. Registered before CORSMiddleware, this sits
# inside it, so the 500 reaches the page with its CORS headers and a real status.
@app.middleware("http")
async def json_server_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001 — the last line of defence; the traceback is logged
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "The server hit an unexpected error."})


# CORS.
#
# The previous configuration was `allow_origins=["*"]` together with
# `allow_credentials=True`. That pairing is not permissive, it is invalid: the spec forbids
# a wildcard `Access-Control-Allow-Origin` on a credentialed request, so a browser rejects
# the response and the call fails — the exact opposite of what the wildcard was reaching
# for. Starlette silently drops the wildcard in that case too.
#
# So the two modes are made explicit. With `CORS_ORIGINS=*` (local development) credentials
# are off and any origin may call. With an explicit origin list (production) credentials are
# allowed, because the origins are known.
#
# `CORS_ORIGIN_REGEX` exists for Vercel preview deployments, whose hostname changes on every
# push and therefore cannot be enumerated in advance.
_allow_any = settings.allow_any_origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_any else settings.cors_origins,
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_credentials=not _allow_any,
    allow_methods=["*"],
    allow_headers=["*"],
    # The submission response carries the job location; without this the browser hides it.
    expose_headers=["Location"],
)

# Security headers on every response.
#
# The API returns JSON and images, never HTML a browser should render, so the policy is as
# tight as it can be: nothing may be loaded (`default-src 'none'`), nothing may frame it,
# content types are never guessed, and no referrer leaks a signed image URL to another site.
# HSTS is harmless over plain HTTP locally (browsers ignore it there) and pins HTTPS in
# production.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "cross-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith(("/docs", "/redoc")):
        # The interactive API docs are an HTML page that loads its own scripts.
        del response.headers["Content-Security-Policy"]
    return response


# Claim photographs, served back to the review screen.
#
# `image_paths` stores `uploads/<uuid>.jpg`, so this route is what makes those rows
# resolvable. Before it existed the review timeline rendered an <img> for every piece of
# evidence and every one of them 404'd.
#
# A route rather than `StaticFiles`, for one reason that turned up under test and applies
# equally in production: a mount binds its directory **at import time**. Anything that
# relocates storage afterwards — a test fixture, a container that mounts its disk late —
# leaves the mount serving a path that no longer holds the files, and the symptom is a 404
# for evidence that exists. Resolving per request costs a `stat` and cannot drift.
#
# Served only with a valid signature. The claim response carries URLs signed with an expiry
# (`platform_backend/security.py`), minted only after the caller was allowed to read that
# claim — an `<img>` tag cannot send an Authorization header, so the URL carries the proof.
@app.get(f"/{UPLOAD_URL_PREFIX}/{{name}}", tags=["uploads"])
def get_upload(name: str, exp: Optional[str] = None, sig: Optional[str] = None):
    if not verify_asset(name, exp, sig):
        raise HTTPException(status_code=403, detail="This link is invalid or has expired.")
    root = upload_dir().resolve()
    # The stored names are generated hex, so a legitimate request never contains a
    # separator. Rejecting them outright is a stronger check than normalising and hoping.
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise HTTPException(status_code=404, detail="Not found")

    target = (root / name).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    # Private, and no longer than the link is valid: a shared cache must never hand one
    # claimant's photograph to another.
    return FileResponse(target, headers={"Cache-Control": "private, max-age=600"})


@app.get("/health", tags=["ops"])
def health():
    """Liveness. Deliberately does no I/O — a health check that touches the database
    reports the database's problems as the process's, and a platform then restarts a
    perfectly healthy container it cannot fix."""
    return {"status": "ok", "service": settings.PROJECT_NAME}


@app.get("/ready", tags=["ops"])
def ready():
    """
    Readiness: can this process actually serve a claim?

    Distinct from liveness on purpose. The database is required — without it nothing can be
    persisted. A missing Gemini key is reported but does *not* make the service unready: the
    pipeline degrades to an honest `not_enough_information` rather than a fabricated verdict,
    and the read-only endpoints still work. The retrieval index is advisory in the same way.
    """
    checks = {}
    try:
        from sqlalchemy import text

        from platform_backend.db.session import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {type(e).__name__}"

    checks["gemini_key"] = "present" if settings.GEMINI_API_KEY else "missing"
    index = getattr(app.state, "index", None)
    checks["retrieval_index"] = (
        "loaded" if index is not None and getattr(index, "meta", None) else "empty"
    )
    # A too-short AURELIX_JWT_SECRET is refused when a token is signed, so every sign-in
    # fails while everything else looks healthy. It makes the service unready: no one can
    # get in to submit a claim. Never the key itself, only its state.
    from platform_backend.services.auth import signing_key_status
    checks["signing_key"] = signing_key_status()
    ready_ = checks["database"] == "ok" and checks["signing_key"] != "too_short"
    return {"ready": ready_, "checks": checks}


@app.on_event("startup")
def on_startup():
    init_db()
    from platform_backend.db.session import SessionLocal

    # Persist one row per model call. Subscribed here, not at import, so importing the app
    # in a script or a test does not start writing telemetry by accident.
    from platform_backend.services import llm_telemetry
    llm_telemetry.install()

    # Accounts from AURELIX_SEED_USERS. Never a default password: with the variable unset,
    # only the demo sign-in exists.
    from platform_backend.services.auth import seed_users
    seed_db = SessionLocal()
    try:
        seeded = seed_users(seed_db)
        if seeded:
            print(f"[Auth] {seeded} account(s) seeded from AURELIX_SEED_USERS")
    except ValueError as exc:
        print(f"[Auth] AURELIX_SEED_USERS ignored: {exc}")
    finally:
        seed_db.close()

    # The retrieval index is built offline by `python -m agent_core.tools.build_index` and
    # only loaded here. The previous startup hook re-indexed a CSV into a TF-IDF store on
    # every boot, and nothing consumed the result.
    #
    # Loading is best-effort on purpose: a missing or out-of-date index must not stop the
    # API from accepting claims. Retrieval informs a reviewer; it does not decide anything,
    # so its absence degrades context rather than correctness.
    # Jobs left running by a process that died cannot be resumed by a single-process
    # pool. Failing them is honest; leaving them `running` means a client polls forever
    # and no operator ever finds out.
    from platform_backend.db.session import SessionLocal
    from platform_backend.services.jobs import reap_orphans, requeue_pending
    db = SessionLocal()
    try:
        reaped = reap_orphans(db)
        if reaped:
            print(f"[Jobs] marked {reaped} interrupted job(s) as failed")
        requeued = requeue_pending(db)
        if requeued:
            print(f"[Jobs] restarted {requeued} job(s) that were queued but never began")
    finally:
        db.close()

    from agent_core.retrieval.collections import IndexBundle
    try:
        # Serving mode: never embed documents in the web process — see HybridRetriever.index.
        app.state.index = IndexBundle.load(embed_documents=False)
        counts = {n: m.count for n, m in app.state.index.meta.items()}
        print(f"[Retrieval] index loaded: {counts or 'empty — run tools.build_index'}")
    except ValueError as e:
        app.state.index = IndexBundle()
        print(f"[Retrieval] index NOT loaded: {e}")

    print(f"[CORS] origins={settings.cors_origins} credentials={not _allow_any}")
    from platform_backend.services.auth import signing_key_status
    if signing_key_status() == "too_short":
        print("[ERROR] AURELIX_JWT_SECRET is shorter than 32 characters — every sign-in will "
              "fail. Set it to e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`.")
    if not settings.GEMINI_API_KEY:
        print("[WARN] GEMINI_API_KEY is not set — perception will fail and every claim "
              "will return not_enough_information.")


@app.on_event("shutdown")
def on_shutdown():
    # Drain in-flight analysis rather than dropping work already paid for out of a
    # 20-request daily budget.
    from platform_backend.services.jobs import shutdown
    shutdown(wait=True)

    from platform_backend.services import llm_telemetry
    llm_telemetry.uninstall()


app.include_router(auth_router)
app.include_router(v1_router)
app.include_router(router)
