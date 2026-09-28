import io

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.models.user import User
from app.services.resume_version_service import ResumeVersionService
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


@pytest.fixture
def auth_headers(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "versionuser@example.com", "password": "StrongPass123!"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "versionuser@example.com", "password": "StrongPass123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_resume_and_job(db, user_id):
    resume = Resume(
        user_id=user_id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1800,
        storage_path="/tmp/resume.docx",
        text_content=(
            "Summary: Python engineer with backend experience and API design focus. "
            "Experience: Built REST APIs using FastAPI, SQLAlchemy, and PostgreSQL. "
            "Skills: Python, FastAPI, SQLAlchemy, PostgreSQL, Docker. "
            "Education: Bachelor's Degree in Computer Science."
        ),
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=user_id,
        source_type="paste",
        text_content="Python engineer with FastAPI, SQLAlchemy, PostgreSQL, API design, backend systems, and Docker experience.",
        normalized_text="python engineer with fastapi, sqlalchemy, postgresql, api design, backend systems, docker",
        prompt_injection_detected=False,
        status="processed",
    )
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    return resume, job


def test_resume_version_master_and_tailored_versions_are_created(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="versionuser@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _seed_resume_and_job(db, user.id)
    db.close()

    master = client.post(
        "/api/v1/resume-versions/master",
        headers=auth_headers,
        json={"resume_id": resume.id},
    )
    assert master.status_code == 201
    assert master.json()["version_name"] == "master"

    tailored = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id, "version_name": "company-a"},
    )
    assert tailored.status_code == 201
    payload = tailored.json()
    assert payload["version_name"] == "company-a"
    assert payload["truthfulness_status"] in {"SUPPORTED", "REQUIRES_REVIEW"}


def test_same_company_role_versions_are_preserved_and_keep_jd_associations(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    resume, job_one = _seed_resume_and_job(db, user.id)
    job_one.role_name = "Backend Engineer"
    job_one.company_name = "Company A"
    job_two = JobDescription(
        user_id=user.id,
        source_type="paste",
        role_name="Backend Developer",
        company_name="Company A",
        text_content="FastAPI backend developer with Docker.",
        normalized_text="fastapi backend developer with docker",
        prompt_injection_detected=False,
        status="processed",
    )
    db.add(job_two)
    db.commit()
    db.refresh(job_one)
    db.refresh(job_two)
    resume_id = resume.id
    job_one_id = job_one.id
    job_two_id = job_two.id
    db.close()

    first = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume_id, "job_description_id": job_one_id, "version_name": "v1"},
    )
    second = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume_id, "job_description_id": job_two_id, "version_name": "v2"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    versions = client.get(f"/api/v1/resume-versions/resume/{resume_id}", headers=auth_headers).json()
    ids = {item["id"] for item in versions}
    assert first.json()["id"] in ids
    assert second.json()["id"] in ids
    assert first.json()["job_description_id"] == job_one_id
    assert second.json()["job_description_id"] == job_two_id
    assert any(item["is_master"] for item in versions)


def test_restore_creates_history_snapshot_without_mutating_master(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    resume, job = _seed_resume_and_job(db, user.id)
    db.close()

    master = client.post("/api/v1/resume-versions/master", headers=auth_headers, json={"resume_id": resume.id})
    tailored = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id, "version_name": "tailored"},
    )
    restored = client.post(
        "/api/v1/resume-versions/restore",
        headers=auth_headers,
        json={"resume_id": resume.id, "version_id": tailored.json()["id"]},
    )

    assert master.status_code == 201
    assert restored.status_code == 200
    assert restored.json()["created_version_id"]
    db = TestingSessionLocal()
    refreshed_resume = db.get(Resume, resume.id)
    restored_versions = db.query(ResumeVersion).filter(ResumeVersion.resume_id == resume.id).all()
    db.close()
    assert refreshed_resume.text_content == resume.text_content
    assert len(restored_versions) >= 3
    assert any(item.id == tailored.json()["id"] for item in restored_versions)


def test_two_versions_have_independent_downloadable_docx_and_pdf_artifacts(tmp_path):
    db = TestingSessionLocal()
    user = User(email="artifact-history@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    document = Document()
    document.add_paragraph("SUMMARY")
    document.add_paragraph("Python developer with experience building web applications.")
    source = io.BytesIO()
    document.save(source)
    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    source_key = storage.put_upload(user_id=user.id, kind="resumes", filename="resume.docx", data=source.getvalue(), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    resume = Resume(user_id=user.id, filename="resume.docx", original_filename="resume.docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", file_size=len(source.getvalue()), storage_path=source_key, text_content="SUMMARY\nPython developer with experience building web applications.", status="processed")
    db.add(resume)
    db.commit()
    db.refresh(resume)
    versions = []
    original_sentence = "Python developer with experience building web applications."
    for text, proposed in [
        ("SUMMARY\nPython developer with experience building web applications.", original_sentence),
        ("SUMMARY\nFastAPI Python developer with experience building web applications.", "FastAPI Python developer with experience building web applications."),
    ]:
        version = ResumeVersion(user_id=user.id, resume_id=resume.id, version_name="history", source_type="tailored", original_text=resume.text_content, tailored_text=text, final_text=text, validation_summary={"accepted_changes": [{"original_content": original_sentence, "proposed_content": proposed}]}, truthfulness_status="SUPPORTED", finalization_status="approved", status="approved")
        db.add(version)
        db.commit()
        db.refresh(version)
        versions.append(version)

    service = ResumeVersionService(db, storage=storage)
    docx_keys = [service.generate_docx(version) for version in versions]
    pdf_keys = [service.generate_pdf(version) for version in versions]
    docx_texts = ["\n".join(paragraph.text for paragraph in Document(io.BytesIO(storage.get_bytes(key))).paragraphs) for key in docx_keys]
    pdf_texts = ["\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(storage.get_bytes(key))).pages) for key in pdf_keys]

    assert docx_keys[0] != docx_keys[1]
    assert pdf_keys[0] != pdf_keys[1]
    assert "FastAPI Python developer" not in docx_texts[0]
    assert "FastAPI Python developer" in docx_texts[1]
    assert "FastAPI Python developer" not in pdf_texts[0]
    assert "FastAPI Python developer" in pdf_texts[1]


def test_user_cannot_access_another_users_version_or_artifact(client, auth_headers):
    db = TestingSessionLocal()
    other = User(email="other-version-user@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)
    resume = Resume(
        user_id=other.id,
        filename="other.docx",
        original_filename="other.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1,
        storage_path="missing/other.docx",
        text_content="Other user's resume.",
        status="processed",
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    version = ResumeVersion(
        user_id=other.id,
        resume_id=resume.id,
        version_name="other-version",
        source_type="tailored",
        original_text=resume.text_content,
        tailored_text=resume.text_content,
        final_text=resume.text_content,
        truthfulness_status="SUPPORTED",
        finalization_status="approved",
        status="approved",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    version_id = version.id
    db.close()

    assert client.get(f"/api/v1/resume-versions/{version_id}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/resume-versions/{version_id}/download/docx", headers=auth_headers).status_code == 404
    assert client.delete(f"/api/v1/resume-versions/{version_id}", headers=auth_headers).status_code == 404


def test_resume_version_compare_and_restore_work(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="versionuser@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _seed_resume_and_job(db, user.id)
    db.close()

    tailored = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id, "version_name": "company-a"},
    )
    version_id = tailored.json()["id"]

    compare = client.post(
        "/api/v1/resume-versions/compare",
        headers=auth_headers,
        json={"base_version_id": version_id, "target_version_id": version_id},
    )
    assert compare.status_code == 200
    assert compare.json()["diff"]

    restore = client.post(
        "/api/v1/resume-versions/restore",
        headers=auth_headers,
        json={"resume_id": resume.id, "version_id": version_id},
    )
    assert restore.status_code == 200
    assert "restored_text" in restore.json()


def test_resume_version_delete_keeps_master(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="versionuser@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume, job = _seed_resume_and_job(db, user.id)
    db.close()

    tailored = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id, "version_name": "delete-me"},
    )
    version_id = tailored.json()["id"]

    deleted = client.delete(f"/api/v1/resume-versions/{version_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["id"] == version_id

    versions = client.get(f"/api/v1/resume-versions/resume/{resume.id}", headers=auth_headers)
    assert versions.status_code == 200
    assert all(item["id"] != version_id for item in versions.json())
    assert any(item["is_master"] for item in versions.json())


def test_resume_version_validation_blocks_unsupported_content(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="versionuser@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1500,
        storage_path="/tmp/resume.docx",
        text_content=(
            "Summary: Backend engineer. Experience: Built systems. Skills: Python. Education: B.Sc."
        ),
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=user.id,
        source_type="paste",
        text_content="Kubernetes engineer with AWS and Terraform, leading 10 systems with 200% revenue impact.",
        normalized_text="kubernetes engineer with aws terraform",
        prompt_injection_detected=False,
        status="processed",
    )
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    db.close()

    response = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id, "version_name": "unsupported"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["truthfulness_status"] in {"SUPPORTED", "REQUIRES_REVIEW"}
    assert payload["finalization_status"] in {"draft", "approved", "ready", "blocked"}


def test_tailored_version_does_not_add_unverified_jd_claims(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="versionuser@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="missing/resume.docx",
        text_content="Summary: Backend engineer. Experience: Built REST services. Skills: Python. Education: B.Tech.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=user.id,
        source_type="paste",
        text_content="Backend engineer with FastAPI and Kubernetes experience.",
        normalized_text="backend engineer with fastapi and kubernetes experience",
        prompt_injection_detected=False,
        status="processed",
    )
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    db.close()

    response = client.post(
        "/api/v1/resume-versions/tailored",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )

    assert response.status_code == 201
    assert "FastAPI" not in response.json()["final_text"]
    assert "Kubernetes" not in response.json()["final_text"]


def test_generate_docx_applies_accepted_change_without_rebuilding_layout(tmp_path):
    db = TestingSessionLocal()
    user = User(
        email="docx@example.com",
        password_hash=hash_password("StrongPass123!"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    document = Document()
    document.add_heading("Resume", level=1)
    paragraph = document.add_paragraph()
    run = paragraph.add_run("Experienced Python engineer.")
    run.bold = True
    source_buffer = io.BytesIO()
    document.save(source_buffer)

    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    source_key = storage.put_upload(
        user_id=user.id,
        kind="resumes",
        filename="resume.docx",
        data=source_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=len(source_buffer.getvalue()),
        storage_path=source_key,
        text_content="Experienced Python engineer.",
        status="processed",
        docx_layout_preserved=True,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    version = ResumeVersion(
        user_id=user.id,
        resume_id=resume.id,
        version_name="tailored",
        source_type="tailored",
        status="draft",
        finalization_status="ready",
        original_text="Experienced Python engineer.",
        tailored_text="Experienced Python backend engineer.",
        final_text="Experienced Python backend engineer.",
        diff_text="Original: Experienced Python engineer.\n\nTailored: Experienced Python backend engineer.",
        validation_summary={
            "accepted_changes": [{
                "original_content": "Python",
                "proposed_content": "Python backend",
            }]
        },
        truthfulness_status="SUPPORTED",
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    generated_key = ResumeVersionService(db, storage=storage).generate_docx(version)
    generated = Document(io.BytesIO(storage.get_bytes(generated_key)))

    assert generated.paragraphs[0].style.name == "Heading 1"
    assert generated.paragraphs[1].text == "Experienced Python backend engineer."
    assert generated.paragraphs[1].runs[0].bold is True


def test_apply_docx_modifications_handles_summary_insertions_without_original_text():
    document = Document()
    document.add_heading("Resume", level=1)
    document.add_paragraph("Skills: Python, FastAPI")

    modification = {
        "original_content": "",
        "proposed_content": "SUMMARY\nPython engineer focused on backend APIs and FastAPI services.",
        "action_type": "ADD_SUMMARY",
    }

    errors = ResumeVersionService._apply_docx_modifications(document, [modification])

    assert errors == []
    assert "SUMMARY" in "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Python engineer focused on backend APIs and FastAPI services." in "\n".join(
        paragraph.text for paragraph in document.paragraphs
    )


def test_apply_docx_modifications_preserves_order_and_applies_multiple_sections():
    document = Document()
    for heading, content in [
        ("SUMMARY", "Python developer with experience building web applications."),
        ("SKILLS", "Python, SQL"),
        ("PROJECTS", "Built a resume analyzer."),
        ("EDUCATION", "Bachelor of Computer Science."),
    ]:
        document.add_paragraph(heading)
        document.add_paragraph(content)

    modifications = [
        {
            "original_content": "Python developer with experience building web applications.",
            "proposed_content": "Python developer with experience building FastAPI web applications.",
        },
        {"original_content": "Python, SQL", "proposed_content": "Python, FastAPI, SQL"},
        {"original_content": "Built a resume analyzer.", "proposed_content": "Built a FastAPI resume analyzer."},
    ]

    assert ResumeVersionService._apply_docx_modifications(document, modifications) == []
    texts = [paragraph.text for paragraph in document.paragraphs]

    assert texts == [
        "SUMMARY",
        "Python developer with experience building FastAPI web applications.",
        "SKILLS",
        "Python, FastAPI, SQL",
        "PROJECTS",
        "Built a FastAPI resume analyzer.",
        "EDUCATION",
        "Bachelor of Computer Science.",
    ]
    assert texts.count("Built a FastAPI resume analyzer.") == 1


def test_apply_docx_modifications_changes_only_matching_similar_paragraph():
    document = Document()
    document.add_paragraph("PROJECTS")
    document.add_paragraph("Built web applications for internal teams.")
    document.add_paragraph("Built web applications for customer workflows.")

    errors = ResumeVersionService._apply_docx_modifications(document, [{
        "original_content": "Built web applications for customer workflows.",
        "proposed_content": "Built FastAPI web applications for customer workflows.",
    }])

    assert errors == []
    assert [paragraph.text for paragraph in document.paragraphs] == [
        "PROJECTS",
        "Built web applications for internal teams.",
        "Built FastAPI web applications for customer workflows.",
    ]


def test_apply_docx_modifications_preserves_table_structure_and_other_cells():
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "SKILLS"
    table.cell(0, 1).text = "Python"
    table.cell(1, 0).text = "PROJECT"
    table.cell(1, 1).text = "Built web applications."

    errors = ResumeVersionService._apply_docx_modifications(document, [{
        "original_content": "Built web applications.",
        "proposed_content": "Built FastAPI web applications.",
    }])

    assert errors == []
    assert len(document.tables) == 1
    assert len(document.tables[0].rows) == 2
    assert document.tables[0].cell(0, 0).text == "SKILLS"
    assert document.tables[0].cell(0, 1).text == "Python"
    assert document.tables[0].cell(1, 0).text == "PROJECT"
    assert document.tables[0].cell(1, 1).text == "Built FastAPI web applications."


def test_generate_docx_no_modification_keeps_original_content(tmp_path):
    db = TestingSessionLocal()
    user = User(email="noop-docx@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    document = Document()
    document.add_paragraph("SUMMARY")
    document.add_paragraph("Python developer with experience building web applications.")
    source_buffer = io.BytesIO()
    document.save(source_buffer)
    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    source_key = storage.put_upload(
        user_id=user.id,
        kind="resumes",
        filename="resume.docx",
        data=source_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=len(source_buffer.getvalue()),
        storage_path=source_key,
        text_content="SUMMARY\nPython developer with experience building web applications.",
        status="processed",
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    version = ResumeVersion(
        user_id=user.id,
        resume_id=resume.id,
        version_name="noop",
        source_type="tailored",
        original_text=resume.text_content,
        tailored_text=resume.text_content,
        final_text=resume.text_content,
        validation_summary={"accepted_changes": []},
        truthfulness_status="SUPPORTED",
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    generated = Document(io.BytesIO(storage.get_bytes(ResumeVersionService(db, storage=storage).generate_docx(version))))

    assert [paragraph.text for paragraph in generated.paragraphs] == [
        "SUMMARY",
        "Python developer with experience building web applications.",
    ]


def test_download_docx_returns_persisted_tailored_artifact(client, auth_headers, tmp_path, monkeypatch):
    db = TestingSessionLocal()
    user = db.query(User).first()
    document = Document()
    document.add_paragraph("SUMMARY")
    document.add_paragraph("Python developer with experience building web applications.")
    document.add_paragraph("SKILLS")
    document.add_paragraph("Python, SQL")
    document.add_paragraph("PROJECTS")
    document.add_paragraph("Built a resume analyzer for internal workflows.")
    document.add_paragraph("EDUCATION")
    document.add_paragraph("Bachelor of Computer Science.")
    source_buffer = io.BytesIO()
    document.save(source_buffer)
    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    source_key = storage.put_upload(
        user_id=user.id,
        kind="resumes",
        filename="resume.docx",
        data=source_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=len(source_buffer.getvalue()),
        storage_path=source_key,
        text_content="SUMMARY\nPython developer with experience building web applications.\nSKILLS\nPython, SQL\nPROJECTS\nBuilt a resume analyzer for internal workflows.\nEDUCATION\nBachelor of Computer Science.",
        status="processed",
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    version = ResumeVersion(
        user_id=user.id,
        resume_id=resume.id,
        version_name="tailored",
        source_type="tailored",
        original_text=resume.text_content,
        tailored_text="SUMMARY\nPython developer with experience building FastAPI web applications.\nSKILLS\nPython, FastAPI, SQL\nPROJECTS\nBuilt a resume analyzer for internal workflows.\nEDUCATION\nBachelor of Computer Science.",
        final_text="SUMMARY\nPython developer with experience building FastAPI web applications.\nSKILLS\nPython, FastAPI, SQL\nPROJECTS\nBuilt a resume analyzer for internal workflows.\nEDUCATION\nBachelor of Computer Science.",
        validation_summary={"accepted_changes": [{
            "original_content": "Python developer with experience building web applications.",
            "proposed_content": "Python developer with experience building FastAPI web applications.",
        }, {
            "original_content": "Python, SQL",
            "proposed_content": "Python, FastAPI, SQL",
        }]},
        truthfulness_status="SUPPORTED",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    db.close()

    monkeypatch.setattr("app.services.resume_version_service.StorageService", lambda: storage)
    response = client.get(f"/api/v1/resume-versions/{version.id}/download/docx", headers=auth_headers)

    assert response.status_code == 200
    downloaded = Document(io.BytesIO(response.content))
    extracted = "\n".join(paragraph.text for paragraph in downloaded.paragraphs)
    assert "FastAPI web applications" in extracted
    assert "Python, FastAPI, SQL" in extracted
    assert "Python developer with experience building web applications." not in extracted
    assert [paragraph.text for paragraph in downloaded.paragraphs] == [
        "SUMMARY",
        "Python developer with experience building FastAPI web applications.",
        "SKILLS",
        "Python, FastAPI, SQL",
        "PROJECTS",
        "Built a resume analyzer for internal workflows.",
        "EDUCATION",
        "Bachelor of Computer Science.",
    ]

    refreshed = TestingSessionLocal().get(ResumeVersion, version.id)
    assert refreshed.document_path
    assert refreshed.document_path != source_key
    persisted = Document(io.BytesIO(storage.get_bytes(refreshed.document_path)))
    assert "FastAPI web applications" in "\n".join(paragraph.text for paragraph in persisted.paragraphs)

    pdf_response = client.get(f"/api/v1/resume-versions/{version.id}/download/pdf", headers=auth_headers)

    assert pdf_response.status_code == 200
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_response.content)).pages)
    normalized_pdf = " ".join(pdf_text.split())
    assert "FastAPI web applications" in normalized_pdf
    assert "Python developer with experience building web applications." not in normalized_pdf
    assert "Python, FastAPI, SQL" in normalized_pdf
    refreshed = TestingSessionLocal().get(ResumeVersion, version.id)
    assert refreshed.pdf_path
    assert refreshed.pdf_path != source_key


def test_pdf_tailoring_preserves_original_page_geometry_and_unmodified_content(tmp_path):
    db = TestingSessionLocal()
    user = User(
        email="pdf-layout@example.com",
        password_hash=hash_password("StrongPass123!"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    source_doc = pymupdf.open()
    page = source_doc.new_page(width=400, height=300)
    page.insert_text((30, 35), "HAREESH RESUME", fontsize=16)
    original_sentence = (
        "Designed prompt-engineering templates for the LLM inference layer, "
        "mitigating hallucinations to achieve 89% factual response accuracy "
        "across 50 evaluated queries."
    )
    page.insert_textbox(
        pymupdf.Rect(30, 65, 370, 120),
        original_sentence,
        fontsize=9.48,
        fontname="helv",
        lineheight=1.0,
    )
    page.insert_text((30, 155), "EDUCATION", fontsize=10)
    source_buffer = io.BytesIO()
    source_doc.save(source_buffer)
    source_doc.close()

    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    source_key = storage.put_upload(
        user_id=user.id,
        kind="resumes",
        filename="resume.pdf",
        data=source_buffer.getvalue(),
        content_type="application/pdf",
    )
    resume = Resume(
        user_id=user.id,
        filename="resume.pdf",
        original_filename="resume.pdf",
        content_type="application/pdf",
        file_size=len(source_buffer.getvalue()),
        storage_path=source_key,
        text_content="HAREESH RESUME\\n" + original_sentence + "\\nEDUCATION",
        status="processed",
        docx_layout_preserved=False,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    change = {
        "action_type": "RESUME_EDIT",
        "original_content": original_sentence,
        "proposed_content": (
            "Designed prompt templates for the LLM inference layer, mitigating hallucinations "
            "to achieve 89% factual accuracy across 50 queries."
        ),
    }
    service = ResumeVersionService(db, storage=storage)
    result = service.build_pdf_bytes(
        resume,
        resume.text_content,
        [change],
    )

    version = ResumeVersion(
        user_id=user.id,
        resume_id=resume.id,
        version_name="native-pdf",
        source_type="tailored",
        original_text=resume.text_content,
        tailored_text=resume.text_content.replace(original_sentence, change["proposed_content"]),
        final_text=resume.text_content.replace(original_sentence, change["proposed_content"]),
        validation_summary={"accepted_changes": [change]},
        truthfulness_status="SUPPORTED",
        status="approved",
        finalization_status="approved",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    saved_key = service.generate_pdf(version)
    saved_result = storage.get_bytes(saved_key)
    db.close()

    original_pdf = pymupdf.open(stream=source_buffer.getvalue(), filetype="pdf")
    tailored_pdf = pymupdf.open(stream=result, filetype="pdf")
    assert len(tailored_pdf) == len(original_pdf) == 1
    assert tailored_pdf[0].rect == original_pdf[0].rect

    original_header = original_pdf[0].search_for("HAREESH RESUME")[0]
    tailored_header = tailored_pdf[0].search_for("HAREESH RESUME")[0]
    assert tailored_header == original_header
    assert tailored_pdf[0].search_for("EDUCATION")
    assert "Designed prompt templates for the LLM inference layer" in tailored_pdf[0].get_text()
    assert original_sentence not in tailored_pdf[0].get_text()

    saved_pdf = pymupdf.open(stream=saved_result, filetype="pdf")
    assert len(saved_pdf) == 1
    assert saved_pdf[0].rect == original_pdf[0].rect
    assert "Designed prompt templates for the LLM inference layer" in saved_pdf[0].get_text()
    saved_header = saved_pdf[0].search_for("HAREESH RESUME")[0]
    assert saved_header == original_header
    original_pdf.close()
    tailored_pdf.close()
    saved_pdf.close()

