from fastapi import FastAPI

from app.core.config import settings


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}