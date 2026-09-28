import io

import pytest
from docx import Document
from docx.shared import Pt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.services.tailoring_service import TailoringService
from app.services.resume_version_service import ResumeVersionService

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


@pytest.fixture
def auth_headers(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "tailor@example.com", "password": "StrongPass123!"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "tailor@example.com", "password": "StrongPass123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_resume_and_jd(db, user_id: int):
    resume = Resume(
        user_id=user_id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1500,
        storage_path="/tmp/resume.docx",
        text_content=(
            "Senior Python engineer with FastAPI, SQLAlchemy, and PostgreSQL. "
            "Built backend services and REST APIs for internal customer workflows. "
            "Led API design, integration work, and operational support."
        ),
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=user_id,
        source_type="paste",
        text_content=(
            "Python engineer with FastAPI, SQLAlchemy, PostgreSQL, Docker, and API design experience. "
            "Strong ownership of backend systems and operational excellence."
        ),
        normalized_text=(
            "python engineer with fastapi, sqlalchemy, postgresql, docker, api design, backend systems"
        ),
        prompt_injection_detected=False,
        status="processed",
    )
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    return resume, job


def test_document_previews_return_the_uploaded_docx_format(client, auth_headers, monkeypatch):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

    resume, job = _create_resume_and_jd(db, user.id)
    document = Document()
    document.add_paragraph("EDUCATION")
    document.add_paragraph("Bachelor of Technology - Computer Science and Engineering")
    document.add_paragraph("TECHNICAL SKILLS")
    document.add_paragraph("Python, FastAPI")
    resume.text_content = (
        "EDUCATION\n"
        "Bachelor of Technology - Computer Science and Engineering\n"
        "TECHNICAL SKILLS\n"
        "Python, FastAPI"
    )
    db.commit()
    resume_id = resume.id
    job_id = job.id
    buffer = io.BytesIO()
    document.save(buffer)
    source_bytes = buffer.getvalue()
    db.close()

    monkeypatch.setattr(
        "app.services.storage_service.StorageService.get_bytes",
        lambda self, key: source_bytes,
    )

    original = client.get(f"/api/v1/resumes/{resume_id}/preview", headers=auth_headers)
    assert original.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in original.headers["content-type"]

    tailored = client.post(
        "/api/v1/tailoring/document-preview",
        headers=auth_headers,
        json={
            "resume_id": resume_id,
            "job_description_id": job_id,
            "accepted_change_ids": [],
            "format": "docx",
        },
    )
    assert tailored.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in tailored.headers["content-type"]


def test_tailoring_preview_generates_supported_changes(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _create_resume_and_jd(db, user.id)
    db.close()

    response = client.post(
        "/api/v1/tailoring/preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["original_text"]
    assert payload["modifications"]
    categories = {item["change_category"] for item in payload["modifications"]}
    assert categories.issubset({"KEEP", "ENHANCE", "REPHRASE", "ALIGN", "DE-EMPHASIZE", "USER_REVIEW"})
    assert all(item["truthfulness_status"] in {"SUPPORTED", "REQUIRES_REVIEW", "USER_VERIFIED", "UNSUPPORTED"} for item in payload["modifications"])
    assert all("original_content" in item and "proposed_content" in item for item in payload["modifications"])
    assert payload["validation_errors"] == []


def test_tailoring_rejects_unsupported_claims(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Built customer-facing web applications and support workflows.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=user.id,
        source_type="paste",
        text_content="Kubernetes engineer with AWS, Terraform, and distributed systems experience.",
        normalized_text="kubernetes engineer with aws terraform distributed systems",
        prompt_injection_detected=False,
        status="processed",
    )
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    db.close()

    response = client.post(
        "/api/v1/tailoring/preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert any(item["change_category"] == "USER_REVIEW" for item in payload["modifications"])
    assert any(item["truthfulness_status"] in {"UNSUPPORTED", "REQUIRES_REVIEW"} for item in payload["modifications"])


def test_tailoring_accepts_selected_changes_and_restores_original(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _create_resume_and_jd(db, user.id)
    db.close()

    preview = client.post(
        "/api/v1/tailoring/preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )
    change_id = preview.json()["modifications"][0]["id"]

    decision = client.patch(
        f"/api/v1/tailoring/changes/{change_id}",
        headers=auth_headers,
        json={"accepted": True},
    )
    assert decision.status_code == 200

    final = client.post(
        "/api/v1/tailoring/finalize",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id, "accepted_change_ids": [change_id]},
    )
    assert final.status_code == 200
    final_payload = final.json()
    assert final_payload["final_text"]
    assert final_payload["accepted_changes"]

    restore = client.post(
        "/api/v1/tailoring/restore",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )
    assert restore.status_code == 200
    assert restore.json()["restored_text"] == preview.json()["original_text"]


def test_tailoring_decision_persists_across_preview_requests(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _create_resume_and_jd(db, user.id)
    db.close()

    first = client.post(
        "/api/v1/tailoring/preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    ).json()
    change_id = first["modifications"][0]["id"]
    assert client.patch(
        f"/api/v1/tailoring/changes/{change_id}",
        headers=auth_headers,
        json={"accepted": True},
    ).status_code == 200

    refreshed = client.post(
        "/api/v1/tailoring/preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    ).json()
    stored = next(item for item in refreshed["modifications"] if item["id"] == change_id)
    assert stored["decision"] == "ACCEPTED"
    assert stored["accepted"] is True


def test_tailoring_review_change_requires_verification_before_acceptance(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume = Resume(user_id=user.id, filename="resume.docx", original_filename="resume.docx", content_type="text/plain", file_size=1, storage_path="/tmp/r", text_content="Python developer.", status="processed")
    job = JobDescription(user_id=user.id, source_type="paste", text_content="Kubernetes required.", normalized_text="kubernetes required", status="processed")
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    db.close()

    preview = client.post("/api/v1/tailoring/preview", headers=auth_headers, json={"resume_id": resume.id, "job_description_id": job.id}).json()
    review = next(item for item in preview["modifications"] if item["truthfulness_status"] in {"UNSUPPORTED", "REQUIRES_REVIEW"})
    blocked = client.patch(f"/api/v1/tailoring/changes/{review['id']}", headers=auth_headers, json={"accepted": True})
    assert blocked.status_code == 409
    verified = client.patch(f"/api/v1/tailoring/changes/{review['id']}", headers=auth_headers, json={"user_verified": True})
    assert verified.status_code == 200
    accepted = client.patch(f"/api/v1/tailoring/changes/{review['id']}", headers=auth_headers, json={"accepted": True})
    assert accepted.status_code == 200


def test_tailoring_only_auto_applies_supported_or_user_verified_changes(monkeypatch):
    service = TailoringService(db=None)
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Built customer-facing applications and support workflows.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=1,
        source_type="paste",
        text_content="Requires docker and kubernetes expertise.",
        normalized_text="requires docker and kubernetes expertise",
        prompt_injection_detected=False,
        status="processed",
    )

    monkeypatch.setattr(service, "_extract_jd_requirements", lambda job: ["docker", "kubernetes"])
    monkeypatch.setattr(service, "_find_supporting_evidence", lambda text, requirement: [text])
    monkeypatch.setattr(service, "_build_targeted_summary", lambda original_text, job: "")
    monkeypatch.setattr(service, "_propose_rewording", lambda original_text, requirement, evidence: "Built customer-facing applications and support workflows with Docker.")
    monkeypatch.setattr(service, "_classify_change", lambda requirement, evidence, original_text, proposed: "ALIGN")
    monkeypatch.setattr(service, "_truthfulness_status", lambda category, proposed, evidence: "REQUIRES_REVIEW")

    preview = service.preview(resume, job)

    assert preview["auto_applied_change_ids"] == []
    assert all(item["truthfulness_status"] == "REQUIRES_REVIEW" for item in preview["modifications"] if item["target_jd_requirement"] in {"docker", "kubernetes"})


def test_tailoring_user_verified_requires_explicit_application_verification():
    service = TailoringService(db=None)
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Built customer-facing applications and support workflows.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=1,
        source_type="paste",
        text_content="Requires docker and kubernetes expertise.",
        normalized_text="requires docker and kubernetes expertise",
        prompt_injection_detected=False,
        status="processed",
    )

    preview = {
        "original_text": resume.text_content,
        "modifications": [{
            "id": "uv-1",
            "proposed_content": "Deployed Docker containers in production.",
            "truthfulness_status": "USER_VERIFIED",
            "user_verified": False,
            "target_jd_requirement": "docker",
            "change_category": "ALIGN",
        }],
        "auto_applied_change_ids": [],
    }
    service.preview = lambda *args, **kwargs: preview

    final = service.finalize(resume, job, ["uv-1"])
    assert final["accepted_changes"] == []
    assert final["final_text"] == resume.text_content

    preview["modifications"][0]["user_verified"] = True
    final = service.finalize(resume, job, ["uv-1"])
    assert final["accepted_changes"]
    assert final["accepted_changes"][0]["truthfulness_status"] == "USER_VERIFIED"
    assert final["accepted_changes"][0]["user_verified"] is True


def test_tailoring_rejected_change_is_excluded_from_final_text():
    service = TailoringService(db=None)
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Built web applications. Led API integrations.",
        status="processed",
    )
    job = JobDescription(
        user_id=1,
        source_type="paste",
        text_content="Backend engineer",
        normalized_text="backend engineer",
        prompt_injection_detected=False,
        status="processed",
    )
    service.preview = lambda *args, **kwargs: {
        "original_text": resume.text_content,
        "modifications": [
            {"id": "accept", "original_content": "web applications", "proposed_content": "FastAPI web applications", "truthfulness_status": "SUPPORTED", "change_category": "ALIGN", "target_jd_requirement": "fastapi"},
            {"id": "reject", "original_content": "API integrations", "proposed_content": "Kubernetes integrations", "truthfulness_status": "SUPPORTED", "change_category": "ALIGN", "target_jd_requirement": "kubernetes"},
        ],
        "auto_applied_change_ids": [],
    }

    result = service.finalize(resume, job, ["accept"])

    assert "FastAPI web applications" in result["final_text"]
    assert "Kubernetes integrations" not in result["final_text"]
    assert [change["id"] for change in result["accepted_changes"]] == ["accept"]


def test_tailoring_explicit_reject_all_does_not_fall_back_to_auto_changes():
    service = TailoringService(db=None)
    resume = Resume(text_content="Built web applications.")
    job = JobDescription(id=1, text_content="FastAPI", normalized_text="fastapi")
    service.preview = lambda *args, **kwargs: {
        "original_text": resume.text_content,
        "modifications": [{
            "id": "auto-1",
            "original_content": "web applications",
            "proposed_content": "FastAPI web applications",
            "truthfulness_status": "SUPPORTED",
            "change_category": "ALIGN",
            "target_jd_requirement": "fastapi",
        }],
        "auto_applied_change_ids": ["auto-1"],
    }

    result = service.finalize(resume, job, [])

    assert result["accepted_changes"] == []
    assert result["final_text"] == resume.text_content


def test_tailoring_does_not_invent_unsupported_technology_claims():
    service = TailoringService(db=None)
    original = "Built customer-facing applications and support workflows."

    result = service._propose_rewording(original, "docker", [original])

    assert result == original
    assert "containerized deployment support" not in result.lower()


def test_tailoring_validation_blocks_fictional_claims(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="tailor@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _create_resume_and_jd(db, user.id)
    db.close()

    preview = client.post(
        "/api/v1/tailoring/preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )
    payload = preview.json()
    assert payload["validation_errors"] == []
    assert all("kubernetes" not in item["proposed_content"].lower() for item in payload["modifications"]) 



def test_existing_professional_summary_is_tailored_to_target_role():
    service = TailoringService(db=None)
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        text_content=(
            "Hareesh Teja\n"
            "PROFESSIONAL SUMMARY\n"
            "Computer Science graduate experienced in building responsive web applications.\n"
            "TECHNICAL SKILLS\n"
            "Python, FastAPI, PostgreSQL, RAG, LLMs\n"
            "PROJECTS\n"
            "AI Customer Support Bot"
        ),
        status="processed",
        storage_path="/tmp/resume.docx",
    )
    job = JobDescription(
        id=1,
        user_id=1,
        role_name="AI Automation Intern",
        source_type="paste",
        text_content="AI Automation Intern Python FastAPI RAG LLM workflow automation.",
        normalized_text="ai automation intern python fastapi rag llm workflow automation",
        status="processed",
    )

    preview = service.preview(resume, job)

    summary_changes = [
        item for item in preview["modifications"]
        if item.get("target_jd_requirement") == "AI Automation Intern"
    ]
    assert summary_changes
    change = summary_changes[0]
    assert change["action_type"] == "RESUME_EDIT"
    assert "Computer Science graduate" in change["proposed_content"]
    assert "AI Automation Intern" in change["proposed_content"]
    assert change["original_content"]


def test_docx_summary_insertion_keeps_section_order_and_heading_style():
    document = Document()
    heading = document.add_paragraph("PROJECTS")
    heading.runs[0].bold = True
    heading.runs[0].font.size = Pt(11)
    body = document.add_paragraph("Built an automation platform using Python.")
    body.runs[0].font.size = Pt(9)

    errors = ResumeVersionService._apply_docx_modifications(
        document,
        [{
            "action_type": "ADD_SUMMARY",
            "original_content": "",
            "proposed_content": "Computer Science graduate targeting AI Automation Intern.",
        }],
    )

    assert errors == []
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert texts[:3] == [
        "PROFESSIONAL SUMMARY",
        "Computer Science graduate targeting AI Automation Intern.",
        "PROJECTS",
    ]
    assert document.paragraphs[0].runs[0].bold is True
    assert document.paragraphs[0].runs[0].font.size == Pt(11)


def test_docx_validation_catches_lost_unrelated_content():
    document = Document()
    document.add_paragraph("SUMMARY")
    document.add_paragraph("Computer Science graduate.")
    document.add_paragraph("PROJECTS")
    document.add_paragraph("Built an automation platform.")
    errors = ResumeVersionService._validate_generated_docx(
        document,
        [],
        expected_text=(
            "SUMMARY\n"
            "Computer Science graduate.\n"
            "PROJECTS\n"
            "Built an automation platform using Python and FastAPI."
        ),
    )
    assert any("missing resume content" in error.lower() for error in errors)
