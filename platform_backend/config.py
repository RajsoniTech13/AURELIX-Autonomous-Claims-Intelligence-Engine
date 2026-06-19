import os
from pydantic_settings import BaseSettings

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
