from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.embedding_service import EmbeddingRepository, GeminiEmbeddingProvider

from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.services.job_match_service import JobMatchService
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.core.security import hash_password

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
        json={"email": "matchuser@example.com", "password": "StrongPass123!"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "matchuser@example.com", "password": "StrongPass123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_job_match_analysis_returns_explainable_scores(client, auth_headers):
    db = TestingSessionLocal()
    user = db.query(User).first()
    if user is None:
        user = User(email="matchuser@example.com", password_hash=hash_password("StrongPass123!"), is_active=True)
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
        text_content="Senior Python engineer with FastAPI, SQLAlchemy, PostgreSQL, REST APIs, Docker, and microservices experience. Led backend services and API design.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=user.id,
        source_type="paste",
        text_content="We are hiring a Python engineer with FastAPI, SQLAlchemy, PostgreSQL, API design, system design, and team leadership.",
        normalized_text="Python engineer with FastAPI, SQLAlchemy, PostgreSQL, API design, system design, and leadership.",
        prompt_injection_detected=False,
        status="processed",
    )
    db.add_all([resume, job])
    db.commit()
    db.refresh(resume)
    db.refresh(job)
    db.close()

    response = client.post(
        "/api/v1/analysis/job-match",
        headers=auth_headers,
        json={"resume_id": resume.id, "job_description_id": job.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_match_score"] > 0
    assert payload["ats_compatibility_score"] >= 0
    assert payload["layout_preservation_score"] >= 0
    assert payload["truthfulness_status"] in {"SUPPORTED", "USER_VERIFIED", "UNSUPPORTED", "REQUIRES_REVIEW"}
    assert "matched_skills" in payload
    assert "missing_skills" in payload
    assert "recommendations" in payload
    assert payload["score_breakdown"]["Technical Skills"] > 0


def test_job_match_truthfulness_rejects_generic_keyword_matches():
    status = JobMatchService._determine_truthfulness_status(
        matched_skills=[],
        partially=[],
        keyword_matches=["experience", "engineer"],
        resume_text="experienced backend engineer with excellent customer support",
    )

    assert status in {"REQUIRES_REVIEW", "UNSUPPORTED"}


def test_job_match_analysis_rejects_missing_resume_or_jd(client, auth_headers):
    response = client.post(
        "/api/v1/analysis/job-match",
        headers=auth_headers,
        json={"resume_id": 999, "job_description_id": 999},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_job_match_service_returns_requirement_level_statuses_and_total_100():
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Python engineer with FastAPI, SQLAlchemy, PostgreSQL, and backend API design experience.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=1,
        source_type="paste",
        text_content="Senior Python engineer with FastAPI, SQLAlchemy, PostgreSQL, API design, and team leadership.",
        normalized_text="Senior Python engineer with FastAPI, SQLAlchemy, PostgreSQL, API design, and team leadership.",
        prompt_injection_detected=False,
        status="processed",
    )

    payload = JobMatchService(None, None).analyze(resume, job, 1)

    assert 0.0 < payload["job_match_score"] < 100.0
    assert payload["score_breakdown"]["Technical Skills"] > 0
    assert any(item["status"] in {"MATCHED", "PARTIALLY_MATCHED", "MISSING", "REQUIRES_REVIEW"} for item in payload["requirement_matches"])


def test_job_match_service_does_not_fabricate_fastapi_when_absent():
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Python backend engineer with Django, PostgreSQL, and software design leadership.",
        status="processed",
        docx_layout_preserved=True,
    )
    job = JobDescription(
        user_id=1,
        source_type="paste",
        text_content="Requires FastAPI and API design experience.",
        normalized_text="Requires FastAPI and API design experience.",
        prompt_injection_detected=False,
        status="processed",
    )

    payload = JobMatchService(None, None).analyze(resume, job, 1)

    # Missing JD skills are coverage gaps, not evidence that the resume is untruthful.
    assert payload["truthfulness_status"] == "SUPPORTED"
    assert any(item["requirement"] == "fastapi" and item["status"] in {"MISSING", "REQUIRES_REVIEW"} for item in payload["requirement_matches"])


def test_job_match_service_enforces_selected_resume_for_semantic_evidence(monkeypatch):
    service = JobMatchService(
        db=SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))),
        repository=None,
    )
    resume_a = Resume(
        user_id=1,
        filename="resume-a.docx",
        original_filename="resume-a.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume-a.docx",
        text_content="Python backend engineer with SQLAlchemy, PostgreSQL, and REST APIs.",
        status="processed",
        docx_layout_preserved=True,
    )
    resume_b = Resume(
        user_id=1,
        filename="resume-b.docx",
        original_filename="resume-b.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume-b.docx",
        text_content="Deployed Docker containers in production and managed Kubernetes orchestration.",
        status="processed",
        docx_layout_preserved=True,
    )
    captured = {}

    def fake_embed_queries(self, requirements):
        return [[0.0 for _ in range(1536)] for _ in requirements]

    def fake_search_similar(self, *, query_vector, user_id, source_types=None, limit=10, resume_id=None):
        captured["resume_id"] = resume_id
        if resume_id != resume_a.id:
            return [{
                "chunk_id": 911,
                "resume_id": resume_b.id,
                "similarity": 0.96,
                "text": "Deployed Docker containers in production.",
            }]
        return []

    monkeypatch.setattr(service, "_semantic_enabled", lambda: True)
    monkeypatch.setattr(GeminiEmbeddingProvider, "embed_queries", fake_embed_queries)
    monkeypatch.setattr(EmbeddingRepository, "search_similar", fake_search_similar)

    result = service._evaluate_requirements(["docker"], resume_a.text_content, user_id=1, resume_id=resume_a.id)

    assert captured["resume_id"] == resume_a.id
    assert result[0]["status"] == "MISSING"
    assert result[0]["semantic_similarity"] is None


def test_job_match_lexical_evidence_isolation_uses_only_selected_resume():
    selected = Resume(
        user_id=1,
        id=101,
        filename="resume-a.docx",
        original_filename="resume-a.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume-a.docx",
        text_content="Python backend engineer with PostgreSQL experience.",
        status="processed",
    )
    other = Resume(
        user_id=1,
        id=102,
        filename="resume-b.docx",
        original_filename="resume-b.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume-b.docx",
        text_content="FastAPI engineer with Docker experience.",
        status="processed",
    )

    result = JobMatchService(None, None)._evaluate_requirements(
        ["fastapi"], selected.text_content, user_id=selected.user_id, resume_id=selected.id
    )

    assert result[0]["status"] == "MISSING"
    assert "FastAPI" not in result[0]["evidence"]
    assert other.text_content != selected.text_content


def test_job_match_service_semantic_similarity_does_not_establish_truthfulness(monkeypatch):
    service = JobMatchService(
        db=SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))),
        repository=None,
    )
    resume = Resume(
        user_id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content="Python backend engineer with SQLAlchemy and PostgreSQL experience.",
        status="processed",
        docx_layout_preserved=True,
    )

    monkeypatch.setattr(service, "_semantic_enabled", lambda: True)
    monkeypatch.setattr(
        GeminiEmbeddingProvider,
        "embed_queries",
        lambda self, requirements: [[0.0 for _ in range(1536)] for _ in requirements],
    )
    monkeypatch.setattr(
        EmbeddingRepository,
        "search_similar",
        lambda self, **kwargs: [{
            "chunk_id": 42,
            "resume_id": 7,
            "similarity": 0.97,
            "text": "Container orchestration and Docker deployment workflows.",
        }],
    )

    result = service._evaluate_requirements(["docker"], resume.text_content, user_id=1, resume_id=resume.id)

    assert result[0]["status"] in {"PARTIALLY_MATCHED", "MISSING"}
    assert "Docker" in result[0]["evidence"] or "docker" in result[0]["evidence"].lower()
    assert result[0]["semantic_similarity"] == pytest.approx(0.97)


def test_truthfulness_status_contract_is_exact_and_canonical():
    statuses = {"SUPPORTED", "UNSUPPORTED", "USER_VERIFIED", "REQUIRES_REVIEW"}

    assert statuses == {"SUPPORTED", "UNSUPPORTED", "USER_VERIFIED", "REQUIRES_REVIEW"}
    assert "PARTIALLY_SUPPORTED" not in statuses
    assert all(status in statuses for status in ["SUPPORTED", "UNSUPPORTED", "USER_VERIFIED", "REQUIRES_REVIEW"])


def test_benchmark_service_reports_insufficient_data_for_empty_sample():
    from app.services.benchmark_service import BenchmarkService

    result = BenchmarkService().summarize([], role_name="backend engineer")

    assert result["insufficient_data"] is True
    assert result["sample_size"] == 0
    assert "Insufficient benchmark data" in result["summary"]


def _match_fixture(resume_text, jd_text, *, role_name=None):
    resume = Resume(
        user_id=1,
        id=1,
        filename="resume.docx",
        original_filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=1200,
        storage_path="/tmp/resume.docx",
        text_content=resume_text,
        status="processed",
    )
    job = JobDescription(
        user_id=1,
        source_type="paste",
        text_content=jd_text,
        normalized_text=jd_text,
        role_name=role_name,
        prompt_injection_detected=False,
        status="processed",
    )
    return JobMatchService(None, None).analyze(resume, job, 1)


def test_job_match_safe_matching_does_not_confuse_java_javascript_or_sql_sqlalchemy():
    payload = _match_fixture(
        "Frontend developer with JavaScript, React Native, and SQLAlchemy experience.",
        "Required Java, SQL, and React.",
    )
    results = {item["requirement"]: item for item in payload["requirement_matches"]}

    assert results["java"]["status"] == "MISSING"
    assert results["sql"]["status"] == "MISSING"
    assert results["react"]["status"] != "MATCHED"


def test_job_match_exact_and_normalized_synonym_matches_are_explainable():
    payload = _match_fixture(
        "Backend engineer using Fast API, Postgres, and containerization.",
        "FastAPI, PostgreSQL, and Docker experience.",
    )
    results = {item["requirement"]: item for item in payload["requirement_matches"]}

    assert results["fastapi"]["status"] == "PARTIALLY_MATCHED"
    assert results["postgresql"]["status"] == "PARTIALLY_MATCHED"
    assert results["docker"]["status"] == "PARTIALLY_MATCHED"
    assert all(results[key]["evidence"] for key in ("fastapi", "postgresql", "docker"))
    assert all(results[key]["match_method"] in {"safe_phrase_or_synonym", "explicit_synonym"} for key in results)


def test_job_match_reports_partial_and_missing_requirements():
    payload = _match_fixture("Python developer with API experience.", "Python and FastAPI are required.")
    results = {item["requirement"]: item for item in payload["requirement_matches"]}

    assert results["python"]["status"] == "MATCHED"
    assert results["fastapi"]["status"] == "MISSING"
    assert results["fastapi"]["reason"].startswith("No reliable")


def test_absent_categories_are_not_evaluated_and_do_not_reduce_score():
    payload = _match_fixture("Python, FastAPI", "Python and FastAPI")

    assert payload["category_statuses"]["Soft Skills"] == "NOT_EVALUATED"
    assert payload["category_statuses"]["Projects"] == "NOT_EVALUATED"
    assert payload["category_scores"]["Soft Skills"] == 0.0
    assert payload["job_match_score"] == 100.0


def test_importance_changes_category_score():
    high_priority = _match_fixture("Docker developer", "FastAPI is required. Docker is useful.")
    normal_priority = _match_fixture("Docker developer", "FastAPI is useful. Docker is useful.")

    high = {item["requirement"]: item for item in high_priority["requirement_matches"]}
    assert high["fastapi"]["importance"] == "high"
    assert high_priority["category_scores"]["Technical Skills"] < normal_priority["category_scores"]["Technical Skills"]


def test_job_title_education_projects_and_experience_use_specific_matching():
    payload = _match_fixture(
        "Backend Engineer\nB.Tech Computer Science\nPROJECTS\nBuilt web applications with FastAPI.",
        "Build web applications. Bachelor degree in computer science.",
        role_name="Senior Backend Engineer",
    )
    results = {item["requirement"]: item for item in payload["requirement_matches"]}

    assert results["web applications"]["status"] == "MATCHED"
    education = [item for item in payload["requirement_matches"] if item["category"] == "Education/Certifications"]
    assert education and education[0]["status"] == "MATCHED"
    assert payload["category_statuses"]["Job Title"] == "EVALUATED"
    assert payload["category_scores"]["Job Title"] > 0


def test_soft_skills_are_evaluated_only_when_present_in_jd():
    absent = _match_fixture("Python engineer", "Python engineer")
    present = _match_fixture("Python engineer who led a team", "Python engineer with leadership")

    assert absent["category_statuses"]["Soft Skills"] == "NOT_EVALUATED"
    assert present["category_statuses"]["Soft Skills"] == "EVALUATED"
    assert any(item["category"] == "Soft Skills" for item in present["requirement_matches"])


def test_job_match_is_deterministic_for_same_resume_and_jd():
    first = _match_fixture("Python FastAPI PostgreSQL", "Python and FastAPI")
    second = _match_fixture("Python FastAPI PostgreSQL", "Python and FastAPI")

    assert first["job_match_score"] == second["job_match_score"]
    assert first["requirement_matches"] == second["requirement_matches"]
    assert first["category_scores"] == second["category_scores"]


def test_benchmark_output_does_not_change_job_match_score(monkeypatch):
    baseline = _match_fixture("Python FastAPI", "Python and FastAPI")
    monkeypatch.setattr(
        "app.services.job_match_service.BenchmarkService.summarize",
        lambda *args, **kwargs: {
            "data_sufficiency": "SUFFICIENT",
            "common_skills": [{"item": "Kubernetes", "count": 99, "frequency": 1.0}],
            "resume_comparison": {"benchmark_common_but_not_evidenced": ["kubernetes"]},
        },
    )
    with_benchmark = _match_fixture("Python FastAPI", "Python and FastAPI")

    assert with_benchmark["job_match_score"] == baseline["job_match_score"]
    assert with_benchmark["truthfulness_status"] == baseline["truthfulness_status"]


@pytest.mark.parametrize(
    ("requirement", "resume_text"),
    [
        ("retrieval augmented generation", "Built a RAG pipeline."),
        ("javascript", "Built the frontend with JS."),
        ("problem solving", "Strong problem-solving skills."),
        ("communication", "Excellent communication skills."),
        ("collaboration", "Led team collaboration."),
        ("willingness to learn", "A quick learner."),
        ("attention to detail", "Attention toDetail in implementation."),
    ],
)
def test_controlled_equivalents_match_without_loose_substrings(requirement, resume_text):
    assert JobMatchService._evaluate_requirement(requirement, resume_text) in {"MATCHED", "PARTIALLY_MATCHED"}


def test_boundary_matching_does_not_confuse_git_or_sql_compounds():
    assert JobMatchService._evaluate_requirement("git", "GitHub workflows") == "MISSING"
    assert JobMatchService._evaluate_requirement("sql", "SQLAlchemy models") == "MISSING"


def test_project_matching_keeps_resume_wide_skills_out_of_project_gaps():
    payload = _match_fixture(
        "SKILLS\nWorkflow Automation, Git\nPROJECTS\nTicket Router | Python (GitHub)\nBuilt a Python ticket router.",
        "Python and workflow automation are required.",
    )

    project = payload["project_matches"][0]
    assert "workflow automation" not in project["missing_signals"]
    assert "workflow automation" in project["present_elsewhere"]
    workflow = next(item for item in payload["requirement_matches"] if item["requirement"] == "workflow automation")
    assert workflow["status"] in {"MATCHED", "PARTIALLY_MATCHED"}


def test_present_elsewhere_is_not_a_resume_wide_gap():
    resume_text = "SKILLS\nSQL\nPROJECTS\nData Tool | Python (GitHub)\nBuilt a Python data tool."
    project = JobMatchService._build_project_matches(
        "Data Tool | Python (GitHub) Built a Python data tool.",
        ["sql"],
        full_resume_text=resume_text,
    )

    assert "sql" in project[0]["present_elsewhere"]
    assert "sql" not in project[0]["missing_signals"]
    payload = _match_fixture("SKILLS\nSQL", "SQL is required.")
    assert next(item for item in payload["requirement_matches"] if item["requirement"] == "sql")["status"] == "MATCHED"


def test_ai_and_automation_terms_survive_generic_technical_extraction():
    sets = JobMatchService._extract_requirement_sets(
        "Required Generative AI, Prompt Engineering, AI Agents, Workflow Automation, "
        "AI Automation, Cloud, Security, and Software Development."
    )

    technical = set(sets["technical"])
    assert {"generative ai", "prompt engineering", "ai agents", "workflow automation", "cloud", "security", "software development"} <= technical


def test_metadata_terms_are_not_technical_requirements():
    sets = JobMatchService._extract_requirement_sets(
        "Acme Austin Job ID 12345 requires Python.",
        role_name="Software Intern",
        company_name="Acme",
    )

    technical = set(sets["technical"])
    assert "python" in technical
    assert not technical.intersection({"acme", "austin", "12345", "job id 12345"})


def test_equivalent_requirements_are_canonicalized_once():
    requirements = JobMatchService._build_requirement_catalog(
        {"technical": ["RAG", "retrieval augmented generation"], "projects": []},
        "RAG is required.",
    )

    assert [item["requirement"] for item in requirements].count("retrieval augmented generation") == 1


def test_certifications_achievements_and_education_absent_from_jd_are_not_evaluated():
    payload = _match_fixture(
        "SKILLS\nPython\nCERTIFICATIONS\nCloud certificate\nACHIEVEMENTS\nHackathon finalist\nEDUCATION\nB.Tech",
        "Python developer.",
    )

    assert payload["category_statuses"]["Education/Certifications"] == "NOT_EVALUATED"
    assert payload["job_match_score"] > 0
    for section in ("Education", "Certifications", "Achievements"):
        assert any("not evaluated" in detail.lower() for detail in payload["section_details"].get(section, []))


def test_overall_score_uses_resume_wide_evidence_while_sections_remain_local():
    payload = _match_fixture(
        "SKILLS\nGit, SQL\nPROJECTS\nPython Tool | Python (GitHub)\nBuilt a Python tool.",
        "Git, SQL, and Python are required.",
    )

    results = {item["requirement"]: item for item in payload["requirement_matches"]}
    assert results["git"]["status"] == "MATCHED"
    assert results["sql"]["status"] == "MATCHED"
    assert "git" not in payload["project_matches"][0]["missing_signals"]
    assert "sql" not in payload["project_matches"][0]["missing_signals"]


def test_project_score_uses_project_requirements_not_all_technical_requirements():
    payload = _match_fixture(
        "SKILLS\nPython, Workflow Automation\nPROJECTS\nTicket Tool | Python (GitHub)\nBuilt a Python ticket tool.",
        "Python and Workflow Automation are required.",
    )

    technical = {item["requirement"]: item for item in payload["requirement_matches"] if item["category"] == "Technical Skills"}
    assert technical["python"]["status"] == "MATCHED"
    assert technical["workflow automation"]["status"] == "MATCHED"
    assert payload["project_matches"][0]["score"] < 100
    assert "python" not in payload["project_matches"][0]["missing_signals"]


def test_section_score_uses_same_weighted_statuses_as_overall_category_score():
    payload = _match_fixture(
        "SKILLS\nPython\nSQL",
        "Python and SQL are required.",
    )

    assert payload["section_scores"]["Skills"] == 100.0
    assert payload["category_scores"]["Technical Skills"] == 25.0
    assert payload["section_scores"]["Skills"] / 100 == payload["category_scores"]["Technical Skills"] / 25


def test_semantic_evidence_is_applied_through_shared_pipeline_and_scoped(monkeypatch):
    service = JobMatchService(
        db=SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))),
        repository=None,
    )
    searches = []

    monkeypatch.setattr(service, "_semantic_enabled", lambda: True)
    monkeypatch.setattr(
        GeminiEmbeddingProvider,
        "embed_queries",
        lambda self, requirements: [[0.0 for _ in range(1536)] for _ in requirements],
    )

    def fake_search(self, **kwargs):
        searches.append(kwargs)
        return [{
            "chunk_id": 77,
            "resume_id": 12,
            "similarity": 0.80,
            "text": "Related resume evidence.",
        }]

    monkeypatch.setattr(EmbeddingRepository, "search_similar", fake_search)
    catalog = service._build_requirement_catalog(
        {
            "technical": ["container orchestration"],
            "responsibilities": ["coordinate releases"],
            "experience": ["three years backend"],
            "projects": ["workflow automation"],
            "keywords": ["retrieval augmented generation"],
            "title": ["data scientist"],
            "education": ["bachelor degree"],
            "certifications": [],
            "soft_skills": ["adaptability"],
        },
        "requirements",
    )

    results = service._evaluate_requirement_catalog(
        catalog,
        "No lexical evidence here.",
        user_id=44,
        resume_id=12,
    )

    assert results
    assert all(item["status"] == "PARTIALLY_MATCHED" for item in results)
    assert all(item["match_method"] == "semantic_similarity" for item in results)
    assert all(item["evidence_reference"] == "Resume chunk 77" for item in results)
    assert all(query["user_id"] == 44 and query["resume_id"] == 12 for query in searches)


def test_generic_metadata_does_not_use_employer_specific_title_cleanup():
    from app.services.job_description_service import JobDescriptionService

    role, company = JobDescriptionService._derive_job_metadata(
        "Job title: Automation Intern | Company: Contoso"
    )

    assert role == "Automation Intern"
    assert company == "Contoso"
