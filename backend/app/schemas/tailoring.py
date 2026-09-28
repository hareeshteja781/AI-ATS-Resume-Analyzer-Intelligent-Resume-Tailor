from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TailoringRequest(BaseModel):
    resume_id: int
    job_description_id: int


class TailoringDecision(BaseModel):
    accepted: bool | None = None
    user_verified: bool | None = None


class TailoringFinalizeRequest(BaseModel):
    resume_id: int
    job_description_id: int
    accepted_change_ids: list[str] | None = None


class TailoringDocumentPreviewRequest(TailoringFinalizeRequest):
    format: Literal["docx", "pdf"]


class TailoringModification(BaseModel):
    id: str
    original_content: str
    proposed_content: str
    reason: str
    change_category: str
    supporting_resume_evidence: list[str] = Field(default_factory=list)
    target_jd_requirement: str
    requirement_category: str = ""
    evidence_reference: str | None = None
    evidence: list[str] = Field(default_factory=list)
    truthfulness_status: str
    suggested_action: str = ""
    action_type: str = "RESUME_EDIT"
    accepted: bool = False
    decision: str = "PENDING"
    user_verified: bool = False

    model_config = ConfigDict(from_attributes=True)


class TailoringPreviewResponse(BaseModel):
    original_text: str
    modified_text: str | None = None
    modifications: list[TailoringModification] = Field(default_factory=list)
    auto_applied_change_ids: list[str] = Field(default_factory=list)
    diff: list[dict[str, str]] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    available_keywords: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TailoringFinalizeResponse(BaseModel):
    resume_id: int
    job_description_id: int
    original_text: str
    final_text: str
    accepted_changes: list[TailoringModification] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TailoringRestoreResponse(BaseModel):
    resume_id: int
    job_description_id: int
    restored_text: str

    model_config = ConfigDict(from_attributes=True)
