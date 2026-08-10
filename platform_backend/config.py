import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env into the process environment before Settings is constructed.
#
# `env_file = ".env"` below only populates this Settings object. `agent_core` reads
# GEMINI_API_KEY from os.environ, so without this the API server starts fine, accepts
# uploads, and then fails every perception call with "GEMINI_API_KEY is not set" —
# which is exactly what it did the first time the server was ever actually started.
# The CLI always called load_dotenv(); the web platform never did.
load_dotenv()


class Settings(BaseSettings):
    PROJECT_NAME: str = "AURELIX Claims Intelligence"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./aurelix.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # CSV file paths pointing to agent_core data paths
    CLAIMS_CSV: str = os.getenv("CLAIMS_CSV", "agent_core/data/claims.csv")
    USER_HISTORY_CSV: str = os.getenv("USER_HISTORY_CSV", "agent_core/data/user_history.csv")
    EVIDENCE_REQUIREMENTS_CSV: str = os.getenv("EVIDENCE_REQUIREMENTS_CSV", "agent_core/data/evidence_requirements.csv")
    OUTPUT_CSV: str = os.getenv("OUTPUT_CSV", "agent_core/output/output.csv")

    # ── Deployment ──────────────────────────────────────────────────────────
    # Browser origins allowed to call this API. A comma-separated list; `*` means any.
    #
    # This used to be a hardcoded `["*"]` alongside `allow_credentials=True`, which is not
    # a lax policy — it is a broken one. The CORS spec forbids that combination, so browsers
    # reject the response outright and every cross-origin call fails. See main.py.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # Where decoded claim photographs are written. Ephemeral on a free-tier container;
    # override to a mounted disk or swap `services/uploads.save_image` for object storage.
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", str(REPO_ROOT / "var" / "uploads"))
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", 8 * 1024 * 1024))
    MAX_UPLOAD_FILES: int = int(os.getenv("MAX_UPLOAD_FILES", 6))

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allow_any_origin(self) -> bool:
        return "*" in self.cors_origins

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
