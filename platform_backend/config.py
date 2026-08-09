import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

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
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
