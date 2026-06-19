from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# Ensure project root is in path so we can import platform_backend and agent_core
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from platform_backend.config import settings
from platform_backend.db.session import init_db
from platform_backend.api.routes import router

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
    from agent_core.services.vector_store import index_historical_claims
    index_historical_claims("agent_core/data/sample_claims.csv")

app.include_router(router)
