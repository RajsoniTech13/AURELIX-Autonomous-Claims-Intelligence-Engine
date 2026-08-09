from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# Ensure project root is in path so we can import platform_backend and agent_core
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from platform_backend.config import settings
from platform_backend.db.session import init_db
from platform_backend.api.routes import router
from platform_backend.api.v1 import router as v1_router

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.on_event("shutdown")
def on_shutdown():
    # Drain in-flight analysis rather than dropping work already paid for out of a
    # 20-request daily budget.
    from platform_backend.services.jobs import shutdown
    shutdown(wait=True)


app.include_router(v1_router)
app.include_router(router)
