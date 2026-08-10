import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Ensure project root is in path so we can import platform_backend and agent_core
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from platform_backend.config import settings
from platform_backend.db.session import init_db
from platform_backend.api.routes import router
from platform_backend.api.v1 import router as v1_router
from platform_backend.services.uploads import UPLOAD_URL_PREFIX, upload_dir

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

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
@app.get(f"/{UPLOAD_URL_PREFIX}/{{name}}", tags=["uploads"])
def get_upload(name: str):
    root = upload_dir().resolve()
    # The stored names are generated hex, so a legitimate request never contains a
    # separator. Rejecting them outright is a stronger check than normalising and hoping.
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise HTTPException(status_code=404, detail="Not found")

    target = (root / name).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    # Immutable content under a random name: cache hard, revalidate never.
    return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})


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
    ready_ = checks["database"] == "ok"
    return {"ready": ready_, "checks": checks}


@app.on_event("startup")
def on_startup():
    init_db()

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
    from platform_backend.services.jobs import reap_orphans
    db = SessionLocal()
    try:
        reaped = reap_orphans(db)
        if reaped:
            print(f"[Jobs] marked {reaped} interrupted job(s) as failed")
    finally:
        db.close()

    from agent_core.retrieval.collections import IndexBundle
    try:
        app.state.index = IndexBundle.load()
        counts = {n: m.count for n, m in app.state.index.meta.items()}
        print(f"[Retrieval] index loaded: {counts or 'empty — run tools.build_index'}")
    except ValueError as e:
        app.state.index = IndexBundle()
        print(f"[Retrieval] index NOT loaded: {e}")

    print(f"[CORS] origins={settings.cors_origins} credentials={not _allow_any}")
    if not settings.GEMINI_API_KEY:
        print("[WARN] GEMINI_API_KEY is not set — perception will fail and every claim "
              "will return not_enough_information.")


@app.on_event("shutdown")
def on_shutdown():
    # Drain in-flight analysis rather than dropping work already paid for out of a
    # 20-request daily budget.
    from platform_backend.services.jobs import shutdown
    shutdown(wait=True)


app.include_router(v1_router)
app.include_router(router)
