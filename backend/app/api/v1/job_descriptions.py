from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.core.security import get_current_active_user
from app.db.database import get_db
from app.models.user import User
from app.repositories.job_description_repository import JobDescriptionRepository
from app.schemas.ingestion import JobDescriptionImageResponse, JobDescriptionPaste, JobDescriptionResponse, JobDescriptionUrl, JobDescriptionUrlConfirm, JobDescriptionUrlPreview
from app.services.job_description_service import JobDescriptionService

router = APIRouter(prefix="/job-descriptions", tags=["Job Descriptions"])


@router.get("", response_model=list[JobDescriptionResponse], status_code=status.HTTP_200_OK)
def list_job_descriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[JobDescriptionResponse]:
    repository = JobDescriptionRepository(db)
    items = repository.list_for_user(current_user.id)
    return [JobDescriptionResponse(**{
        "id": item.id,
        "user_id": item.user_id,
        "filename": item.filename,
        "role_name": item.role_name,
        "company_name": item.company_name,
        "source_type": item.source_type,
        "content_type": item.content_type,
        "file_size": item.file_size,
        "storage_path": item.storage_path,
        "text_content": item.text_content,
        "normalized_text": item.normalized_text,
        "url": item.url,
        "source_html": item.source_html,
        "prompt_injection_detected": item.prompt_injection_detected,
        "status": item.status,
        "processing_error": item.processing_error,
    }) for item in items]


@router.post("/paste", response_model=JobDescriptionResponse, status_code=status.HTTP_201_CREATED)
def paste_job_description(
    payload: JobDescriptionPaste,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobDescriptionResponse:
    service = JobDescriptionService(db)
    result = service.create_from_text(current_user.id, payload.text)
    return JobDescriptionResponse(**result)


@router.delete("/{job_description_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job_description(
    job_description_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    JobDescriptionService(db).delete_job_description(job_description_id, current_user.id)


@router.post("/upload", response_model=JobDescriptionResponse, status_code=status.HTTP_201_CREATED)
def upload_job_description(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobDescriptionResponse:
    service = JobDescriptionService(db)
    result = service.create_from_upload(current_user.id, file)
    return JobDescriptionResponse(**result)


@router.post("/images", response_model=JobDescriptionImageResponse, status_code=status.HTTP_201_CREATED)
def upload_job_description_images(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobDescriptionImageResponse:
    service = JobDescriptionService(db)
    result = service.create_from_images(current_user.id, files)
    return JobDescriptionImageResponse(**result)


@router.post("/url", response_model=JobDescriptionUrlPreview, status_code=status.HTTP_200_OK)
def url_job_description(
    payload: JobDescriptionUrl,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobDescriptionUrlPreview:
    service = JobDescriptionService(db)
    result = service.preview_from_url(payload.url)
    return JobDescriptionUrlPreview(**result)


@router.post("/url/preview", response_model=JobDescriptionUrlPreview, status_code=status.HTTP_200_OK)
def preview_job_description_url(
    payload: JobDescriptionUrl,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobDescriptionUrlPreview:
    result = JobDescriptionService(db).preview_from_url(payload.url)
    return JobDescriptionUrlPreview(**result)


@router.post("/url/confirm", response_model=JobDescriptionResponse, status_code=status.HTTP_201_CREATED)
def confirm_job_description_url(
    payload: JobDescriptionUrlConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobDescriptionResponse:
    result = JobDescriptionService(db).confirm_url_import(current_user.id, payload.url, payload.text)
    return JobDescriptionResponse(**result)
