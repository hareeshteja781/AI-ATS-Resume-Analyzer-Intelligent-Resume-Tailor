from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobMatchRequest(BaseModel):
    resume_id: int
    job_description_id: int


class JobMatchResponse(BaseModel):
    id: int
    user_id: int
    resume_id: int
    job_description_id: int
    job_match_score: float
    ats_compatibility_score: float
    layout_preservation_score: float
    truthfulness_status: str
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    partially_matched_skills: list[str] = Field(default_factory=list)
    responsibilities_matched: list[str] = Field(default_factory=list)
    evidence_found: list[str] = Field(default_factory=list)
    important_gaps: list[str] = Field(default_factory=list)
    ats_structure_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    benchmark: dict[str, Any] = Field(default_factory=dict)
    requirement_matches: list[dict[str, Any]] = Field(default_factory=list)
    category_scores: dict[str, float] = Field(default_factory=dict)
    category_statuses: dict[str, str] = Field(default_factory=dict)
    section_scores: dict[str, float] = Field(default_factory=dict)
    section_details: dict[str, list[str]] = Field(default_factory=dict)
    present_sections: list[str] = Field(default_factory=list)
    project_matches: list[dict[str, Any]] = Field(default_factory=list)
    layout_analysis: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class ATSAnalysisRequest(BaseModel):
    resume_id: int
    profile: str = "generic"


class ATSAnalysisResponse(BaseModel):
    profile: str
    profile_description: str
    parser_preview: dict[str, Any]
    compatibility: dict[str, Any]
