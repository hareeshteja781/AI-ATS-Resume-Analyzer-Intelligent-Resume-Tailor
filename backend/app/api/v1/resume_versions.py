from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_active_user
from app.db.database import get_db
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.schemas.versioning import (
    ResumeVersionCompareRequest,
    ResumeVersionCompareResponse,
    ResumeVersionDownloadResponse,
    ResumeVersionFinalizeRequest,
    ResumeVersionRequest,
    ResumeVersionRestoreRequest,
    ResumeVersionResponse,
    ResumeVersionRestoreResponse,
)
from app.services.resume_version_service import ResumeVersionService

router = APIRouter(prefix="/resume-versions", tags=["Resume Versions"])


def _serialize_version(version) -> dict:
    return {
        "id": version.id,
        "user_id": version.user_id,
        "resume_id": version.resume_id,
        "job_description_id": version.job_description_id,
        "resume_filename": version.resume.original_filename if version.resume else None,
        "job_role_name": version.job_description.role_name if version.job_description else None,
        "job_company_name": version.job_description.company_name if version.job_description else None,
        "job_description_text": version.job_description.text_content if version.job_description else None,
        "job_source_html": version.job_description.source_html if version.job_description else None,
        "job_url": version.job_description.url if version.job_description else None,
        "version_name": version.version_name,
        "source_type": version.source_type,
        "status": version.status,
        "finalization_status": version.finalization_status,
        "is_master": version.is_master,
        "is_current": version.is_current,
        "original_text": version.original_text,
        "tailored_text": version.tailored_text,
        "final_text": version.final_text,
        "formatted_text": version.validation_summary.get("formatted_text", version.final_text),
        "diff_text": version.diff_text,
        "document_path": version.document_path,
        "pdf_path": version.pdf_path,
        "validation_summary": version.validation_summary or {},
        "truthfulness_status": version.truthfulness_status,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.post("/master", response_model=ResumeVersionResponse, status_code=status.HTTP_201_CREATED)
def create_master_version(
    payload: ResumeVersionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeVersionResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    service = ResumeVersionService(db)
    version = service.create_master_version(resume)
    return ResumeVersionResponse(**_serialize_version(version))


@router.post("/tailored", response_model=ResumeVersionResponse, status_code=status.HTTP_201_CREATED)
def create_tailored_version(
    payload: ResumeVersionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeVersionResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    job = None
    if payload.job_description_id is not None:
        job = db.query(JobDescription).filter(JobDescription.id == payload.job_description_id, JobDescription.user_id == current_user.id).first()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job description not found")

    service = ResumeVersionService(db)
    version = (
        service.create_tailored_version(
            resume,
            job,
            version_name=payload.version_name,
            accepted_change_ids=payload.accepted_change_ids,
        )
        if job
        else service.create_master_version(resume)
    )
    return ResumeVersionResponse(**_serialize_version(version))


@router.get("/history", response_model=list[ResumeVersionResponse], status_code=status.HTTP_200_OK)
def list_tailoring_history(
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ResumeVersionResponse]:
    service = ResumeVersionService(db)
    versions = service.repository.list_history(current_user.id, q)
    return [ResumeVersionResponse(**_serialize_version(item)) for item in versions]


@router.get("/resume/{resume_id}", response_model=list[ResumeVersionResponse], status_code=status.HTTP_200_OK)
def list_resume_versions(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ResumeVersionResponse]:
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    service = ResumeVersionService(db)
    versions = service.list_versions(resume_id, current_user.id)
    return [ResumeVersionResponse(**_serialize_version(item)) for item in versions]


@router.get("/{version_id}", response_model=ResumeVersionResponse, status_code=status.HTTP_200_OK)
def get_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeVersionResponse:
    service = ResumeVersionService(db)
    version = service.get_version(version_id, current_user.id)
    return ResumeVersionResponse(**_serialize_version(version))


@router.delete("/{version_id}", status_code=status.HTTP_200_OK)
def delete_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = ResumeVersionService(db)
    return service.delete_version(version_id, current_user.id)


@router.post("/compare", response_model=ResumeVersionCompareResponse, status_code=status.HTTP_200_OK)
def compare_versions(
    payload: ResumeVersionCompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeVersionCompareResponse:
    service = ResumeVersionService(db)
    result = service.compare_versions(payload.base_version_id, payload.target_version_id, current_user.id)
    return ResumeVersionCompareResponse(**result)


@router.post("/restore", response_model=ResumeVersionRestoreResponse, status_code=status.HTTP_200_OK)
def restore_version(
    payload: ResumeVersionRestoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeVersionRestoreResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    service = ResumeVersionService(db)
    return ResumeVersionRestoreResponse(
        **service.restore_version(resume, payload.version_id, current_user.id)
    )


@router.post("/finalize", response_model=ResumeVersionResponse, status_code=status.HTTP_200_OK)
def finalize_version(
    payload: ResumeVersionFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeVersionResponse:
    service = ResumeVersionService(db)
    version = service.finalize_version(payload.version_id, current_user.id)
    return ResumeVersionResponse(**_serialize_version(version))


@router.get("/{version_id}/preview/pdf", status_code=status.HTTP_200_OK)
def preview_pdf(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = ResumeVersionService(db)
    version = service.get_version(version_id, current_user.id)
    validation = service.validate_resume_text(version.final_text)
    if validation.get("validation_errors"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Version fails validation and cannot be previewed.",
        )
    key = service.generate_pdf(version)
    try:
        payload = service.storage.get_bytes(key)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF preview is not available.") from exc
    return StreamingResponse(
        BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/{version_id}/download/docx", status_code=status.HTTP_200_OK)
def download_docx(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = ResumeVersionService(db)
    version = service.get_version(version_id, current_user.id)
    key = service.generate_docx(version)
    try:
        payload = service.storage.get_bytes(key)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated DOCX is not available.") from exc

    filename = f"{version.version_name or 'resume'}.docx"
    return StreamingResponse(
        BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{version_id}/download/pdf", status_code=status.HTTP_200_OK)
def download_pdf(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = ResumeVersionService(db)
    version = service.get_version(version_id, current_user.id)
    validation = service.validate_resume_text(version.final_text)
    if validation.get("validation_errors"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Version fails truthfulness or formatting validation",
        )

    key = service.generate_pdf(version)
    try:
        payload = service.storage.get_bytes(key)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated PDF is not available.") from exc

    filename = f"{version.version_name or 'resume'}.pdf"
    return StreamingResponse(
        BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
