from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResumeVersionRequest(BaseModel):
    resume_id: int
    job_description_id: int | None = None
    version_id: int | None = None
    version_name: str = "tailored"
    accepted_change_ids: list[str] | None = None


class ResumeVersionCompareRequest(BaseModel):
    base_version_id: int
    target_version_id: int


class ResumeVersionRestoreRequest(BaseModel):
    resume_id: int
    version_id: int


class ResumeVersionFinalizeRequest(BaseModel):
    resume_id: int
    version_id: int


class ResumeVersionResponse(BaseModel):
    id: int
    user_id: int
    resume_id: int
    job_description_id: int | None = None
    resume_filename: str | None = None
    job_role_name: str | None = None
    job_company_name: str | None = None
    job_description_text: str | None = None
    job_source_html: str | None = None
    job_url: str | None = None
    formatted_text: str | None = None
    version_name: str
    source_type: str
    status: str
    finalization_status: str
    is_master: bool = False
    is_current: bool = False
    original_text: str
    tailored_text: str
    final_text: str
    diff_text: str
    document_path: str | None = None
    pdf_path: str | None = None
    validation_summary: dict[str, Any] = Field(default_factory=dict)
    truthfulness_status: str
    created_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ResumeVersionDownloadResponse(BaseModel):
    message: str
    file_path: str
    file_name: str


class ResumeVersionCompareResponse(BaseModel):
    base_version_id: int
    target_version_id: int
    base_version_name: str
    target_version_name: str
    base_text: str
    target_text: str
    diff: list[dict[str, str]] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)


class ResumeVersionRestoreResponse(BaseModel):
    resume_id: int
    restored_version_id: int
    created_version_id: int | None = None
    restored_text: str
    message: str
