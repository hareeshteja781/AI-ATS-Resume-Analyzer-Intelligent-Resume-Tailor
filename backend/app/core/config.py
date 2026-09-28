from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def resolve_env_file() -> str | None:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


class Settings(BaseSettings):
    APP_NAME: str = "AI ATS Resume Analyzer"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str | None = None
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "resume_ats"
    DATABASE_USER: str = "resume_app"
    DATABASE_PASSWORD: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # TEMPORARY LOCAL-DEVELOPMENT CONVENIENCE — remove with /auth/dev-test-login
    # before deploying the project publicly.
    TEST_USER_EMAIL: str = "testcase@gmail.com"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: str = "redis://localhost:6379/0"

    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    GEMINI_EMBEDDING_VERSION: str = "v1"
    GEMINI_TIMEOUT_SECONDS: int = 30
    GEMINI_MAX_RETRIES: int = 2

    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    RATE_LIMIT_PER_MINUTE: int = 120

    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024
    ALLOWED_UPLOAD_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]

    R2_ENDPOINT_URL: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "resume-ats-dev"
    R2_PUBLIC_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def resolved_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        if not self.DATABASE_PASSWORD and not self.is_production:
            return (
                f"postgresql+psycopg://{self.DATABASE_USER}@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            )
        if not self.DATABASE_PASSWORD:
            raise ValueError("DATABASE_PASSWORD must be set in production or when DATABASE_URL is not provided.")
        return (
            f"postgresql+psycopg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> "Settings":
        if self.is_production:
            if not self.JWT_SECRET_KEY:
                raise ValueError("JWT_SECRET_KEY is required in production.")
            if not self.DATABASE_PASSWORD and not self.DATABASE_URL:
                raise ValueError("DATABASE_PASSWORD or DATABASE_URL is required in production.")
            if not self.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is required in production.")
        return self


settings = Settings(_env_file=resolve_env_file())
