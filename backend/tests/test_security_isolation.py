from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.services.embedding_service import VectorSearchService
from app.services.storage_service import LocalStorageBackend, StorageService


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


def _register_and_login(client: TestClient, email: str) -> dict[str, str]:
    password = "StrongPass123!"
    assert client.post("/api/v1/auth/register", json={"email": email, "password": password}).status_code == 201
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _create_owned_objects(client: TestClient, headers: dict[str, str]) -> tuple[int, int, int]:
    resume = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={
            "file": (
                "resume.docx",
                _docx_bytes("Python developer with FastAPI experience."),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resume.status_code == 201
    resume_id = resume.json()["id"]

    job = client.post(
        "/api/v1/job-descriptions/paste",
        headers=headers,
        json={"text": "Backend Engineer with Python and FastAPI experience."},
    )
    assert job.status_code == 201
    job_id = job.json()["id"]

    version = client.post(
        "/api/v1/resume-versions/master",
        headers=headers,
        json={"resume_id": resume_id},
    )
    assert version.status_code == 201
    return resume_id, job_id, version.json()["id"]


def test_user_cannot_read_or_delete_another_users_sources(client):
    user_a = _register_and_login(client, "owner-a@example.com")
    user_b = _register_and_login(client, "owner-b@example.com")
    resume_id, job_id, _ = _create_owned_objects(client, user_a)

    assert all(item["id"] != resume_id for item in client.get("/api/v1/resumes", headers=user_b).json())
    assert all(item["id"] != job_id for item in client.get("/api/v1/job-descriptions", headers=user_b).json())
    assert client.delete(f"/api/v1/resumes/{resume_id}", headers=user_b).status_code == 404
    assert client.delete(f"/api/v1/job-descriptions/{job_id}", headers=user_b).status_code == 404

    cross_user_version = client.post(
        "/api/v1/resume-versions/master",
        headers=user_b,
        json={"resume_id": resume_id},
    )
    assert cross_user_version.status_code == 404


def test_user_cannot_read_download_or_delete_another_users_version(client):
    user_a = _register_and_login(client, "version-a@example.com")
    user_b = _register_and_login(client, "version-b@example.com")
    _, _, version_id = _create_owned_objects(client, user_a)

    assert client.get(f"/api/v1/resume-versions/{version_id}", headers=user_b).status_code == 404
    assert client.get(f"/api/v1/resume-versions/{version_id}/download/docx", headers=user_b).status_code == 404
    assert client.get(f"/api/v1/resume-versions/{version_id}/download/pdf", headers=user_b).status_code == 404
    assert client.delete(f"/api/v1/resume-versions/{version_id}", headers=user_b).status_code == 404


def test_user_cannot_update_another_users_tailoring_change(client):
    user_a = _register_and_login(client, "tailoring-a@example.com")
    user_b = _register_and_login(client, "tailoring-b@example.com")
    resume_id, job_id, _ = _create_owned_objects(client, user_a)

    preview = client.post(
        "/api/v1/tailoring/preview",
        headers=user_a,
        json={"resume_id": resume_id, "job_description_id": job_id},
    )
    assert preview.status_code == 200
    change_id = preview.json()["modifications"][0]["id"]

    response = client.patch(
        f"/api/v1/tailoring/changes/{change_id}",
        headers=user_b,
        json={"accepted": True},
    )
    assert response.status_code == 404
    assert "Python" not in response.text


def test_upload_rejects_path_traversal_and_invalid_signature(client):
    headers = _register_and_login(client, "upload-security@example.com")
    traversal = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={
            "file": (
                "..\\outside.docx",
                _docx_bytes("resume"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert traversal.status_code == 400

    corrupt = client.post(
        "/api/v1/resumes/upload",
        headers=headers,
        files={"file": ("resume.pdf", b"not a pdf", "application/pdf")},
    )
    assert corrupt.status_code == 400
    assert "Traceback" not in corrupt.text
    assert "not a pdf" not in corrupt.text


def test_storage_keys_are_user_scoped_and_traversal_is_rejected(tmp_path: Path):
    storage = StorageService(LocalStorageBackend(tmp_path))
    key = storage.put_upload(
        user_id=42,
        kind="resumes",
        filename="..\\resume.docx",
        data=b"content",
        content_type="application/octet-stream",
    )
    assert key.startswith("users/42/resumes/")
    assert storage.get_bytes(key) == b"content"
    with pytest.raises(ValueError):
        storage.get_bytes("users/43/../42/resumes/secret.docx")
    assert not (tmp_path / "secret.docx").exists()


def test_embedding_search_enforces_user_and_selected_resume_scope():
    candidates = [
        {"user_id": 1, "resume_id": 10, "embedding": [1.0, 0.0]},
        {"user_id": 1, "resume_id": 11, "embedding": [1.0, 0.0]},
        {"user_id": 2, "resume_id": 20, "embedding": [1.0, 0.0]},
    ]
    results = VectorSearchService().search(
        query_vector=[1.0, 0.0],
        candidate_vectors=candidates,
        user_id=1,
        resume_id=10,
    )
    assert len(results) == 1
    assert results[0]["resume_id"] == 10
