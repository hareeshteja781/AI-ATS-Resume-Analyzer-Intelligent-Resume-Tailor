from unittest.mock import patch

import pytest

from app.schemas.ai import JDAnalysis, ResumeEvidence, TailoringProposal
from app.services.ai_service import AIService, AIServiceError


def test_analyze_job_description_validates_structured_gemini_response():
    service = AIService()
    mock_payload = {
        "job_title": "Senior Python Engineer",
        "responsibilities": [
            "Design and build backend services",
            "Review code and mentor engineers",
        ],
        "technical_skills": ["Python", "FastAPI", "SQLAlchemy", "PostgreSQL"],
        "soft_skills": ["Communication", "Leadership"],
        "experience_requirements": ["5+ years in backend systems"],
        "education_requirements": ["Bachelor's degree preferred"],
        "certifications": ["AWS certification optional"],
        "important_keywords": ["Python", "FastAPI", "leadership"],
        "requirement_importance": {"Python": "high", "Leadership": "medium"},
        "requirement_category": {"Python": "technical", "Leadership": "soft"},
    }

    with patch.object(service, "_call_gemini", return_value=mock_payload):
        result = service.analyze_job_description("Senior Python Engineer ...")

    assert isinstance(result, JDAnalysis)
    assert result.job_title == "Senior Python Engineer"
    assert "Python" in result.important_keywords


def test_extract_resume_evidence_validates_structured_output():
    service = AIService()
    mock_payload = {
        "requirement": "Python",
        "evidence_text": "Built FastAPI services in Python for production workloads.",
        "evidence_location": "Experience section",
        "evidence_strength": 0.9,
        "confidence": 0.91,
        "truthfulness_status": "SUPPORTED",
    }

    with patch.object(service, "_call_gemini", return_value=mock_payload):
        result = service.extract_resume_evidence(
            resume_text="Built FastAPI services in Python for production workloads.",
            requirement="Python",
        )

    assert isinstance(result, ResumeEvidence)
    assert result.truthfulness_status == "SUPPORTED"
    assert result.evidence_strength > 0.8


def test_generate_tailoring_proposal_validates_and_keeps_truthfulness():
    service = AIService()
    mock_payload = {
        "original_text": "Led backend engineering teams.",
        "proposed_text": "Led backend engineering teams and improved system reliability.",
        "reason": "Adds measurable operational impact aligned with the role.",
        "change_category": "achievement",
        "supporting_evidence": ["Project impact", "leadership"],
        "target_requirement": "Leadership",
        "truthfulness_status": "USER_VERIFIED",
    }

    with patch.object(service, "_call_gemini", return_value=mock_payload):
        result = service.generate_tailoring_proposal(
            original_text="Led backend engineering teams.",
            requirement="Leadership",
            resume_context="Led backend engineering teams and improved system reliability.",
        )

    assert isinstance(result, TailoringProposal)
    assert result.truthfulness_status == "USER_VERIFIED"
    assert result.proposed_text.startswith("Led backend")


def test_ai_service_raises_clear_error_for_missing_api_key(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.GEMINI_API_KEY", "")
    with pytest.raises(AIServiceError, match="API key"):
        AIService()._require_client()


def test_ai_service_rejects_forbidden_truthfulness_status_values():
    service = AIService()
    mock_payload = {
        "requirement": "Python",
        "evidence_text": "Built FastAPI services in Python for production workloads.",
        "evidence_location": "Experience section",
        "evidence_strength": 0.9,
        "confidence": 0.91,
        "truthfulness_status": "PARTIALLY_SUPPORTED",
    }

    with patch.object(service, "_call_gemini", return_value=mock_payload):
        with pytest.raises(AIServiceError, match="truthfulness_status"):
            service.extract_resume_evidence(
                resume_text="Built FastAPI services in Python for production workloads.",
                requirement="Python",
            )


def test_ai_service_handles_retryable_quota_errors():
    service = AIService()

    with patch.object(service, "_call_gemini", side_effect=AIServiceError("quota exceeded", retryable=True)):
        with pytest.raises(AIServiceError, match="quota exceeded"):
            service.analyze_job_description("Role description")
