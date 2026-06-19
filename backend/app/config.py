import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AURELIX Claims Intelligence"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./aurelix.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # CSV file paths
    CLAIMS_CSV: str = os.getenv("CLAIMS_CSV", "claims/claims.csv")
    USER_HISTORY_CSV: str = os.getenv("USER_HISTORY_CSV", "claims/user_history.csv")
    EVIDENCE_REQUIREMENTS_CSV: str = os.getenv("EVIDENCE_REQUIREMENTS_CSV", "claims/evidence_requirements.csv")
    OUTPUT_CSV: str = os.getenv("OUTPUT_CSV", "claims/output.csv")
    
    class Config:
        env_file = ".env"

settings = Settings()
