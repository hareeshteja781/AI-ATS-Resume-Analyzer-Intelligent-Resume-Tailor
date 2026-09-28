import io

from docx import Document
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.repositories.job_match_repository import JobMatchRepository
from app.services.ats_parser_service import ATSParserService
from app.services.job_match_service import JobMatchService


def fixture_resume(text: str) -> Resume:
    return Resume(
        user_id=1, id=1, filename="resume.docx", original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=len(text), storage_path="", text_content=text, status="processed",
    )


def fixture_job(text: str) -> JobDescription:
    return JobDescription(
        user_id=1, source_type="paste", text_content=text, normalized_text=text,
        prompt_injection_detected=False, status="processed",
    )
def test_soft_skill_variants_collapse_to_one_canonical_requirement():
    catalog = JobMatchService._build_requirement_catalog(
        {"soft_skills": ["work independently", "independently", "analytical", "analytical thinking"]},
        "work independently and analytical skills required",
    )
    requirements = [item["requirement"] for item in catalog]

    assert requirements.count("independent work") == 1
    assert requirements.count("analytical thinking") == 1
    assert JobMatchService._requirement_importance("independent work", "Ability to work independently is mandatory") == "high"
    assert JobMatchService._requirement_importance("independent work", "Ability to work independently is mandatory") == "high"


def test_soft_skill_gap_is_not_duplicated():
    resume = fixture_resume("SOFT SKILLS\nCommunication")
    job = fixture_job("Python engineer with ability to work independently and independently.")
    payload = JobMatchService(None, None).analyze(resume, job, 1)

    gaps = [item["requirement"] for item in payload["requirement_matches"] if item["category"] == "Soft Skills" and item["status"] == "MISSING"]
    assert gaps == ["independent work"]
def test_missing_required_resume_section_is_visible_as_zero_not_hidden():
    resume = fixture_resume("SKILLS\nPython")
    job = fixture_job("Python. Bachelor degree in computer science.")
    payload = JobMatchService(None, None).analyze(resume, job, 1)

    assert payload["section_scores"]["Education"] == 0.0
    assert any("not detected" in detail.lower() for detail in payload["section_details"]["Education"])


def test_education_and_certifications_use_separate_section_signals():
    catalog = JobMatchService._build_requirement_catalog(
        {
            "education": ["bachelor or master degree in computer science or related field"],
            "certifications": ["python certification"],
        },
        "Bachelor or master degree in computer science or related field. Python certification preferred.",
    )

    education = next(item for item in catalog if item["requirement"].startswith("bachelor or master degree"))
    certification = next(item for item in catalog if item["requirement"] == "python certification")

    assert education["category"] == "Education/Certifications"
    assert education["source_categories"] == ["Education"]
    assert certification["category"] == "Education/Certifications"
    assert certification["source_categories"] == ["Certifications"]


def test_bachelor_of_technology_in_computer_science_matches_education():
    resume = fixture_resume(
        "EDUCATION\n"
        "Malla Reddy College of Engineering | JNTUH\n"
        "Bachelor of Technology – Computer Science and Engineering\n"
        "August 2022 – May 2026\n"
        "CGPA: 7.0/10\n"
        "CERTIFICATIONS\n"
        "Oracle Agentic AI Certified Foundations Associate"
    )
    job = fixture_job("Currently pursuing a bachelor or master degree in Computer Science or related field.")

    payload = JobMatchService(None, None).analyze(resume, job, 1)

    assert payload["requirement_matches"][0]["status"] == "MATCHED"
    assert payload["section_scores"]["Education"] == 100.0
    assert payload["section_details"]["Certifications"][0].lower().find("not mentioned in the selected jd") >= 0


def test_missing_jd_requirements_do_not_mark_job_match_as_untruthful():
    resume = fixture_resume("Python developer")
    job = fixture_job("Python and FastAPI")
    payload = JobMatchService(None, None).analyze(resume, job, 1)

    assert payload["truthfulness_status"] == "SUPPORTED"
    fastapi = next(item for item in payload["requirement_matches"] if item["requirement"] == "fastapi")
    assert fastapi["status"] == "MISSING"


def test_project_section_uses_local_project_evidence():
    resume = fixture_resume("SKILLS\nWorkflow Automation\nPROJECTS\nTicket Tool | Python (GitHub)\nBuilt a ticket tool")
    job = fixture_job("Python and workflow automation are required")
    payload = JobMatchService(None, None).analyze(resume, job, 1)

    assert payload["section_scores"]["Projects"] < 100.0
    project = payload["project_matches"][0]
    assert "workflow automation" in project["present_elsewhere"]
def test_section_extraction_does_not_split_on_words_inside_bullets():
    text = (
        "SUMMARY\nBuilt projects for internal automation teams.\n"
        "SKILLS\nPython, SQL\nPROJECTS\nTicket Router\n"
    )
    sections = JobMatchService._extract_resume_sections(text)

    assert sections["summary"] == "Built projects for internal automation teams."
    assert sections["technical skills"] == "Python, SQL"
    assert sections["projects"] == "Ticket Router"


def test_section_extraction_recovers_flattened_uppercase_resume_text():
    text = "Alex Doe PROJECTS Ticket Router | Python Built a ticket tool. TECHNICAL SKILLS Python, SQL EDUCATION B.Tech"
    sections = JobMatchService._extract_resume_sections(text)

    assert sections["projects"].startswith("Ticket Router")
    assert sections["technical skills"] == "Python, SQL"
    assert sections["education"] == "B.Tech"


def test_ats_parser_accepts_common_section_aliases():
    document = Document()
    for line in (
        "Alex Doe", "alex@example.com", "CORE COMPETENCIES", "Python, SQL",
        "WORK HISTORY", "Backend Engineer", "QUALIFICATIONS", "B.Tech Computer Science",
    ):
        document.add_paragraph(line)
    output = io.BytesIO()
    document.save(output)
    result = ATSParserService().analyze_bytes(
        output.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    fields = result["parser_preview"]["fields"]
    assert fields["skills"] == ["Python", "SQL"]
    assert fields["experience"] == ["Backend Engineer"]
    assert fields["education"] == ["B.Tech Computer Science"]
def test_requirement_snapshot_is_reused_after_first_analysis(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=11, email="cache@example.com", password_hash="x", is_active=True))
    resume = fixture_resume("SKILLS\nPython")
    job = fixture_job("Python is required")
    resume.user_id = 11
    job.user_id = 11
    session.add_all([resume, job])
    session.commit()
    session.refresh(job)

    calls = {"count": 0}
    original = JobMatchService._extract_requirement_sets

    def tracked(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(JobMatchService, "_extract_requirement_sets", staticmethod(tracked))
    service = JobMatchService(session, None)
    service.analyze(resume, job, 11)
    session.flush()
    service.analyze(resume, job, 11)

    assert calls["count"] == 1
    assert job.requirement_snapshot["version"] == JobMatchService.REQUIREMENT_SNAPSHOT_VERSION


def test_job_match_repository_updates_existing_pair_instead_of_creating_duplicates():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, email="repo@example.com", password_hash="x", is_active=True))
    session.commit()
    repo = JobMatchRepository(session)
    payload = {
        "job_match_score": 50, "ats_compatibility_score": 80, "layout_preservation_score": 90,
        "truthfulness_status": "SUPPORTED", "matched_skills": [], "missing_skills": [],
        "partially_matched_skills": [], "responsibilities_matched": [], "evidence_found": [],
        "important_gaps": [], "ats_structure_issues": [], "recommendations": [],
        "score_breakdown": {}, "benchmark": {}, "requirement_matches": [],
        "category_scores": {}, "category_statuses": {}, "section_scores": {},
        "section_details": {}, "present_sections": [], "project_matches": [], "layout_analysis": {},
    }
    first = repo.create(user_id=1, resume_id=10, job_description_id=20, payload=payload)
    payload["job_match_score"] = 75
    second = repo.create(user_id=1, resume_id=10, job_description_id=20, payload=payload)

    assert first.id == second.id
    assert second.job_match_score == 75
    assert session.query(__import__("app.models.job_match_result", fromlist=["JobMatchResult"]).JobMatchResult).count() == 1
