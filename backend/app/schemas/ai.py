from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JDAnalysis(BaseModel):
    job_title: str = Field(..., min_length=1)
    responsibilities: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    experience_requirements: list[str] = Field(default_factory=list)
    education_requirements: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    important_keywords: list[str] = Field(default_factory=list)
    requirement_importance: dict[str, str] = Field(default_factory=dict)
    requirement_category: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class JDImageExtraction(BaseModel):
    extracted_text: str = Field(default="")
    job_title: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    technical_tools: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    important_keywords: list[str] = Field(default_factory=list)
    other_requirements: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


ALLOWED_TRUTHFULNESS_STATUSES = {
    "SUPPORTED",
    "UNSUPPORTED",
    "USER_VERIFIED",
    "REQUIRES_REVIEW",
}


class ResumeEvidence(BaseModel):
    requirement: str = Field(..., min_length=1)
    evidence_text: str = Field(..., min_length=1)
    evidence_location: str = Field(..., min_length=1)
    evidence_strength: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    truthfulness_status: Literal["SUPPORTED", "UNSUPPORTED", "USER_VERIFIED", "REQUIRES_REVIEW"]

    model_config = ConfigDict(extra="forbid")


class TailoringProposal(BaseModel):
    original_text: str = Field(..., min_length=1)
    proposed_text: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    change_category: str = Field(..., min_length=1)
    supporting_evidence: list[str] = Field(default_factory=list)
    target_requirement: str = Field(..., min_length=1)
    truthfulness_status: Literal["SUPPORTED", "UNSUPPORTED", "USER_VERIFIED", "REQUIRES_REVIEW"]

    model_config = ConfigDict(extra="forbid")
