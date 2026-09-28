from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_active_user
from app.db.database import get_db
from app.models.resume import Resume
from app.models.user import User
from app.repositories.resume_repository import ResumeRepository
from app.schemas.ingestion import ResumeUploadResponse
from app.services.resume_service import ResumeService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/resumes", tags=["Resumes"])


@router.get("", response_model=list[ResumeUploadResponse], status_code=status.HTTP_200_OK)
def list_resumes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ResumeUploadResponse]:
    repository = ResumeRepository(db)
    resumes = repository.list_for_user(current_user.id)
    return [ResumeUploadResponse(**{
        "id": item.id,
        "user_id": item.user_id,
        "filename": item.filename,
        "original_filename": item.original_filename,
        "content_type": item.content_type,
        "file_size": item.file_size,
        "storage_path": item.storage_path,
        "text_content": item.text_content,
        "status": item.status,
        "processing_error": item.processing_error,
        "docx_layout_preserved": item.docx_layout_preserved,
    }) for item in resumes]


@router.post("/upload", response_model=ResumeUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ResumeUploadResponse:
    service = ResumeService(db)
    payload = service.create_from_upload(current_user.id, file)
    return ResumeUploadResponse(**payload)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    ResumeService(db).delete_resume(resume_id, current_user.id)


@router.get("/{resume_id}/preview", status_code=status.HTTP_200_OK)
def preview_resume_file(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    if not resume.storage_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original resume file is not available.",
        )

    try:
        payload = StorageService().get_bytes(resume.storage_path)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original resume file could not be loaded.",
        ) from exc

    media_type = resume.content_type or "application/octet-stream"
    filename = resume.original_filename or resume.filename or "resume"
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
