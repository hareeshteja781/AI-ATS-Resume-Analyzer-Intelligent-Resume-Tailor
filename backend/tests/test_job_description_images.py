import base64
import io

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers

from app.db.base import Base
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.services.ai_service import AIServiceError
from app.services.job_description_service import JobDescriptionService
from app.services.job_match_service import JobMatchService
from app.services.storage_service import LocalStorageBackend, StorageService
from app.schemas.ai import JDImageExtraction

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def image_upload(name: str, content: bytes = ONE_PIXEL_PNG, content_type: str = "image/png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


@pytest.fixture
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def extraction(text: str, title: str | None = None, required: list[str] | None = None) -> JDImageExtraction:
    return JDImageExtraction(
        extracted_text=text,
        job_title=title,
        required_skills=required or [],
        responsibilities=["Build reliable services"] if "Responsibilities" in text else [],
        technical_tools=required or [],
    )


def test_single_valid_screenshot_is_extracted_and_structured(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.job_description_service.settings.GEMINI_API_KEY", "configured")
    monkeypatch.setattr("app.services.job_description_service.AIService.extract_job_description_image", lambda self, data, mime: extraction("Backend Engineer\nRequirements\nFastAPI and Python", "Backend Engineer", ["FastAPI", "Python"]))
    user = User(email="image@example.com", password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    service = JobDescriptionService(db, storage=storage)
    service._process_chunks_and_embeddings = lambda *args: None

    result = service.create_from_images(user.id, [image_upload("page-1.png")])

    assert result["source_type"] == "image"
    assert result["text_content"] == "Backend Engineer\nRequirements\nFastAPI and Python"
    assert result["normalized_text"]
    assert result["structured_extraction"]["job_title"] == "Backend Engineer"
    assert result["structured_extraction"]["required_skills"] == ["FastAPI", "Python"]
    assert result["source_images"][0]["filename"] == "page-1.png"
    assert result["source_images"][0]["storage_path"] == result["storage_path"]
    assert storage.get_bytes(result["storage_path"]) == ONE_PIXEL_PNG


def test_multiple_screenshots_preserve_order_and_remove_only_overlap(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.job_description_service.settings.GEMINI_API_KEY", "configured")
    responses = iter([
        extraction("Title\nResponsibilities\nBuild APIs\nExperience with Python and FastAPI...", "Backend Engineer", ["Python"]),
        extraction("Experience with Python and FastAPI...\nRequirements\nDocker\nEducation: B.Tech", required=["Docker"]),
    ])
    monkeypatch.setattr("app.services.job_description_service.AIService.extract_job_description_image", lambda self, data, mime: next(responses))
    user = User(email="multi@example.com", password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    service = JobDescriptionService(db, storage=StorageService(backend=LocalStorageBackend(tmp_path)))
    service._process_chunks_and_embeddings = lambda *args: None

    result = service.create_from_images(user.id, [image_upload("1.png"), image_upload("2.png")])

    assert result["text_content"].splitlines() == [
        "Title",
        "Responsibilities",
        "Build APIs",
        "Experience with Python and FastAPI...",
        "Requirements",
        "Docker",
        "Education: B.Tech",
    ]
    assert [item["filename"] for item in result["source_images"]] == ["1.png", "2.png"]


def test_image_output_feeds_existing_job_match_pipeline(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.job_description_service.settings.GEMINI_API_KEY", "configured")
    monkeypatch.setattr("app.services.job_description_service.AIService.extract_job_description_image", lambda self, data, mime: extraction("Backend Engineer\nFastAPI required", "Backend Engineer", ["FastAPI"]))
    user = User(email="pipeline@example.com", password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    service = JobDescriptionService(db, storage=storage)
    service._process_chunks_and_embeddings = lambda *args: None
    result = service.create_from_images(user.id, [image_upload("jd.png")])
    job = db.query(JobDescription).filter(JobDescription.id == result["id"]).one()
    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1,
        storage_path="resume.docx",
        text_content="Backend Engineer with FastAPI experience.",
        status="processed",
    )
    db.add(resume)
    db.commit()

    match = JobMatchService(None, None).analyze(resume, job, user.id)

    assert any(item["requirement"] == "fastapi" and item["status"] == "MATCHED" for item in match["requirement_matches"])


def test_invalid_empty_and_unsupported_images_are_rejected(monkeypatch, db, tmp_path):
    monkeypatch.setattr("app.services.job_description_service.settings.GEMINI_API_KEY", "configured")
    user = User(email="invalid@example.com", password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    service = JobDescriptionService(db, storage=StorageService(backend=LocalStorageBackend(tmp_path)))

    with pytest.raises(Exception, match="empty"):
        service.create_from_images(user.id, [image_upload("empty.png", b"")])
    with pytest.raises(Exception, match="Unsupported image type"):
        service.create_from_images(user.id, [image_upload("resume.pdf", ONE_PIXEL_PNG, "application/pdf")])
    with pytest.raises(Exception, match="corrupt"):
        service.create_from_images(user.id, [image_upload("bad.png", b"not-an-image")])


def test_empty_vision_result_and_vision_failure_are_not_faked(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.job_description_service.settings.GEMINI_API_KEY", "configured")
    user = User(email="failure@example.com", password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    service = JobDescriptionService(db, storage=StorageService(backend=LocalStorageBackend(tmp_path)))

    monkeypatch.setattr("app.services.job_description_service.AIService.extract_job_description_image", lambda self, data, mime: extraction(""))
    with pytest.raises(Exception, match="No readable"):
        service.create_from_images(user.id, [image_upload("empty-content.png")])

    def fail(self, data, mime):
        raise AIServiceError("vision unavailable")

    monkeypatch.setattr("app.services.job_description_service.AIService.extract_job_description_image", fail)
    with pytest.raises(Exception, match="vision unavailable"):
        service.create_from_images(user.id, [image_upload("failed.png")])


def test_image_extraction_requires_configured_vision_service(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.job_description_service.settings.GEMINI_API_KEY", "")
    user = User(email="disabled@example.com", password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    service = JobDescriptionService(db, storage=StorageService(backend=LocalStorageBackend(tmp_path)))

    with pytest.raises(Exception, match="configured Gemini vision service"):
        service.create_from_images(user.id, [image_upload("jd.png")])