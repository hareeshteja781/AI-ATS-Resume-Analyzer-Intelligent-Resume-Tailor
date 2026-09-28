from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ResumeUploadResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    original_filename: str
    content_type: str
    file_size: int
    storage_path: str
    text_content: str
    status: str
    processing_error: str | None = None
    docx_layout_preserved: bool = False

    model_config = ConfigDict(from_attributes=True)


class JobDescriptionPaste(BaseModel):
    text: str = Field(min_length=1, max_length=200000)


class JobDescriptionUrl(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class JobDescriptionUrlConfirm(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    text: str = Field(min_length=1, max_length=200000)


class JobDescriptionUrlPreview(BaseModel):
    source_url: str
    final_url: str
    role_name: str | None = None
    company_name: str | None = None
    text_content: str
    normalized_text: str
    structured_extraction: dict = Field(default_factory=dict)


class JobDescriptionResponse(BaseModel):
    id: int
    user_id: int
    filename: str | None = None
    role_name: str | None = None
    company_name: str | None = None
    source_type: str
    content_type: str | None = None
    file_size: int | None = None
    storage_path: str | None = None
    text_content: str
    normalized_text: str
    url: str | None = None
    source_html: str | None = None
    prompt_injection_detected: bool = False
    status: str
    processing_error: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JobDescriptionImageResponse(JobDescriptionResponse):
    source_images: list[dict] = Field(default_factory=list)
    structured_extraction: dict = Field(default_factory=dict)
