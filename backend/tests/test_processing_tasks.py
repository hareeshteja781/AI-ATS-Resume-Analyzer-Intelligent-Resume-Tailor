import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.services.processing_task_service import ProcessingTaskService

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_processing_task_tracks_progress_and_failure():
    service = ProcessingTaskService(TestingSessionLocal())
    task = service.create_task(user_id=1, task_type="resume_analysis", job_key="resume-analysis-1")

    service.update_progress(task.id, 35)
    service.mark_running(task.id)
    service.mark_failed(task.id, "analysis worker crashed", retryable=True)

    refreshed = service.get_task(task.id)
    assert refreshed.status == "failed"
    assert refreshed.progress == 35
    assert refreshed.retryable is True
    assert refreshed.error_message == "analysis worker crashed"


def test_processing_task_is_idempotent_for_same_job_key():
    service = ProcessingTaskService(TestingSessionLocal())

    first = service.create_task(user_id=1, task_type="resume_analysis", job_key="resume-analysis-dup")
    second = service.create_task(user_id=1, task_type="resume_analysis", job_key="resume-analysis-dup")

    assert first.id == second.id
    assert first.status == "queued"
    assert second.status == "queued"
