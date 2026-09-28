from types import SimpleNamespace
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_production_settings_require_runtime_secrets():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DATABASE_URL="postgresql+psycopg://resume_app@db/resume_ats",
            GEMINI_API_KEY="configured",
        )


def test_cors_origins_parse_from_deployment_environment():
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="https://resume.example.com, https://preview.example.com",
    )
    assert settings.ALLOWED_ORIGINS == [
        "https://resume.example.com",
        "https://preview.example.com",
    ]


def test_configured_cors_origin_is_allowed():
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_readiness_returns_ready_when_database_and_redis_are_available(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _query):
            return None

    monkeypatch.setattr("app.main.engine.connect", lambda: Connection())
    monkeypatch.setattr("app.main.redis.from_url", lambda _url: SimpleNamespace(ping=lambda: True))

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_service_unavailable_when_dependency_fails(monkeypatch):
    def fail_connect():
        raise ConnectionError("database unavailable")

    monkeypatch.setattr("app.main.engine.connect", fail_connect)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Required infrastructure is unavailable."}


def test_worker_registers_expected_tasks():
    from worker.celery_app import celery_app

    assert "resume_ats.health" in celery_app.tasks
    assert "resume_ats.analyze_job_match" in celery_app.tasks
    assert "resume_ats.generate_docx" in celery_app.tasks
    assert "resume_ats.generate_pdf" in celery_app.tasks