from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "AI ATS Resume Analyzer"

    DATABASE_HOST: str
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}"
            f"/{self.DATABASE_NAME}"
        )


settings = Settings()