import base64
import io

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.resume import Resume
from app.models.user import User
from app.services.ats_parser_service import ATSParserService
from app.services.storage_service import LocalStorageBackend, StorageService

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
        json={"email": "ats@example.com", "password": "StrongPass123!"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "ats@example.com", "password": "StrongPass123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def docx_bytes(builder) -> bytes:
    document = Document()
    builder(document)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def clean_resume(document):
    document.add_paragraph("Alex Doe")
    document.add_paragraph("alex@example.com | +1 555 010 1234")
    document.add_paragraph("SUMMARY")
    document.add_paragraph("Python engineer building reliable web applications.")
    document.add_paragraph("SKILLS")
    document.add_paragraph("Python, FastAPI, SQL")
    document.add_paragraph("EXPERIENCE")
    document.add_paragraph("Backend Engineer | 2022 - 2025")
    document.add_paragraph("PROJECTS")
    document.add_paragraph("Resume parser project")
    document.add_paragraph("EDUCATION")
    document.add_paragraph("BSc Computer Science")


def test_parser_preview_extracts_structured_fields_without_inventing_content():
    result = ATSParserService().analyze_bytes(
        docx_bytes(clean_resume),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    preview = result["parser_preview"]

    assert preview["fields"]["name"] == "Alex Doe"
    assert preview["fields"]["contact"]["emails"] == ["alex@example.com"]
    assert preview["fields"]["skills"] == ["Python", "FastAPI", "SQL"]
    assert preview["fields"]["professional_summary"] == "Python engineer building reliable web applications."
    assert preview["fields"]["projects"] == ["Resume parser project"]
    assert preview["missing_fields"] == []
    assert "Kubernetes" not in preview["raw_text"]


def test_parser_preview_reports_missing_standard_headings_and_symbols():
    result = ATSParserService().analyze_text("Alex Doe\nContact: alex@example.com\nPython ® ® ®", source_format="text")
    preview = result["parser_preview"]
    checks = {item["id"]: item for item in result["compatibility"]["checks"]}

    assert "skills" in preview["missing_fields"]
    assert "projects" in preview["missing_fields"]
    assert checks["standard_section_headings"]["status"] == "warning"
    assert checks["unusual_symbols"]["status"] == "warning"


def test_two_column_resume_reports_reading_order_risk():
    def build(document):
        clean_resume(document)
        columns = document.sections[0]._sectPr.xpath("./w:cols")[0]
        columns.set(qn("w:num"), "2")

    result = ATSParserService().analyze_bytes(docx_bytes(build), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    checks = {item["id"]: item for item in result["compatibility"]["checks"]}

    assert result["parser_preview"]["metadata"]["columns"] == 2
    assert checks["multiple_columns"]["status"] == "warning"
    assert checks["reading_order"]["status"] == "fail"


def test_table_resume_preserves_table_block_order_and_reports_table_risk():
    def build(document):
        document.add_paragraph("SUMMARY")
        document.add_paragraph("Before table")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "SKILLS"
        table.cell(0, 1).text = "Python"
        document.add_paragraph("After table")

    result = ATSParserService().analyze_bytes(docx_bytes(build), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    preview = result["parser_preview"]
    checks = {item["id"]: item for item in result["compatibility"]["checks"]}
    blocks = preview["metadata"]["blocks"]

    assert [block["text"] for block in blocks] == ["SUMMARY", "Before table", "SKILLS | Python", "After table"]
    assert preview["metadata"]["tables"] == 1
    assert checks["tables"]["status"] == "warning"


def test_header_footer_and_image_only_resume_are_reported():
    def header_footer(document):
        document.add_paragraph("Alex Doe")
        document.sections[0].header.paragraphs[0].text = "Confidential Resume"
        document.sections[0].footer.paragraphs[0].text = "Page 1"

    header_result = ATSParserService().analyze_bytes(docx_bytes(header_footer), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    header_checks = {item["id"]: item for item in header_result["compatibility"]["checks"]}
    assert header_checks["headers_footers"]["status"] == "warning"
    assert header_result["parser_preview"]["metadata"]["headers_footers"] == ["Confidential Resume", "Page 1"]

    def image_only(document):
        document.add_picture(io.BytesIO(TINY_PNG))

    image_result = ATSParserService().analyze_bytes(docx_bytes(image_only), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    image_checks = {item["id"]: item for item in image_result["compatibility"]["checks"]}
    assert image_result["parser_preview"]["metadata"]["images"] == 1
    assert image_checks["text_extractability"]["status"] == "fail"
    assert image_checks["image_only"]["status"] == "fail"


def test_profiles_report_different_check_sets_but_share_deterministic_extraction():
    source = docx_bytes(clean_resume)
    service = ATSParserService()
    generic = service.analyze_bytes(source, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", profile="generic")
    greenhouse = service.analyze_bytes(source, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", profile="greenhouse")
    workday = service.analyze_bytes(source, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", profile="workday")

    assert generic["parser_preview"]["fields"] == greenhouse["parser_preview"]["fields"] == workday["parser_preview"]["fields"]
    assert "headers_footers" in {item["id"] for item in generic["compatibility"]["checks"]}
    assert "headers_footers" not in {item["id"] for item in greenhouse["compatibility"]["checks"]}
    assert generic["compatibility"]["ats_score"] == 100.0
    assert isinstance(workday["compatibility"]["ats_score"], float)


def test_ats_score_is_derived_from_check_statuses():
    result = ATSParserService().analyze_text("Alex Doe\nNo standard sections", source_format="text")
    checks = result["compatibility"]["checks"]
    values = {"pass": 100.0, "warning": 50.0, "fail": 0.0}
    expected = round(sum(values[item["status"]] for item in checks) / len(checks), 2)
    assert result["compatibility"]["ats_score"] == expected
    assert result["compatibility"]["ats_score"] != 100.0


def test_ats_test_lab_reports_accuracy_and_risks():
    service = ATSParserService()
    result = service.run_test_lab([
        {
            "name": "clean-single-column",
            "source_bytes": docx_bytes(clean_resume),
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "expected_text": "Alex Doe Python FastAPI Resume parser project",
        },
    ])

    assert result["fixture_count"] == 1
    assert result["results"][0]["extraction_accuracy"] == 100.0
    assert result["results"][0]["missing_expected_tokens"] == []
    assert "parsing_risks" in result["results"][0]


def test_parser_preview_api_returns_separate_parser_and_compatibility_sections(client, auth_headers, tmp_path, monkeypatch):
    db = TestingSessionLocal()
    user = db.query(User).first()
    storage = StorageService(backend=LocalStorageBackend(tmp_path))
    source_key = storage.put_upload(
        user_id=user.id,
        kind="resumes",
        filename="resume.docx",
        data=docx_bytes(clean_resume),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    resume = Resume(
        user_id=user.id,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1,
        storage_path=source_key,
        text_content="Alex Doe",
        status="processed",
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    db.close()
    monkeypatch.setattr("app.api.v1.analysis.ATSParserService", lambda: ATSParserService(storage=storage))

    response = client.post(
        "/api/v1/analysis/ats/parser-preview",
        headers=auth_headers,
        json={"resume_id": resume.id, "profile": "greenhouse"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "greenhouse"
    assert payload["parser_preview"]["fields"]["name"] == "Alex Doe"
    assert payload["compatibility"]["ats_score"] >= 0
    assert payload["parser_preview"] != payload["compatibility"]