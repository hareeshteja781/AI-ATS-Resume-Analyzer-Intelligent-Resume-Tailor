from collections import defaultdict
from time import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
import redis

from app.api.v1.analysis import router as analysis_router
from app.api.v1.auth import router as auth_router
from app.api.v1.job_descriptions import router as job_descriptions_router
from app.api.v1.resume_versions import router as resume_versions_router
from app.api.v1.resumes import router as resumes_router
from app.api.v1.tailoring import router as tailoring_router
from app.api.v1.tasks import router as tasks_router
from app.core.config import settings
from app.db.database import engine


def build_rate_limit_middleware():
    requests_by_ip: dict[str, list[float]] = defaultdict(list)

    async def rate_limit_middleware(request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time()
        recent_requests = [ts for ts in requests_by_ip[client_ip] if now - ts < 60]
        if len(recent_requests) >= settings.RATE_LIMIT_PER_MINUTE:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
        recent_requests.append(now)
        requests_by_ip[client_ip] = recent_requests
        return await call_next(request)

    return rate_limit_middleware


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)

app.middleware("http")(build_rate_limit_middleware())
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(resumes_router, prefix="/api/v1")
app.include_router(job_descriptions_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(tailoring_router, prefix="/api/v1")
app.include_router(resume_versions_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        redis.from_url(settings.REDIS_URL).ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Required infrastructure is unavailable.") from exc
    return {"status": "ready"}