from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_active_user
from app.db.database import get_db
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.schemas.tailoring import (
    TailoringDecision,
    TailoringDocumentPreviewRequest,
    TailoringFinalizeRequest,
    TailoringFinalizeResponse,
    TailoringPreviewResponse,
    TailoringRequest,
    TailoringRestoreResponse,
)
from app.services.tailoring_service import TailoringService

router = APIRouter(prefix="/tailoring", tags=["Tailoring"])


@router.post("/preview", response_model=TailoringPreviewResponse, status_code=status.HTTP_200_OK)
def preview_tailoring(
    payload: TailoringRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TailoringPreviewResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    job = db.query(JobDescription).filter(JobDescription.id == payload.job_description_id, JobDescription.user_id == current_user.id).first()
    if not resume or not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume or job description not found")

    service = TailoringService(db)
    computed = service.preview(resume, job)
    return TailoringPreviewResponse(**computed)


@router.patch("/changes/{modification_id}", status_code=status.HTTP_200_OK)
def update_change_decision(
    modification_id: str,
    payload: TailoringDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = TailoringService(db)
    if not service.modification_belongs_to_user(modification_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tailoring change not found")
    try:
        return service.change_decision(
            modification_id,
            payload.accepted,
            payload.user_verified,
            current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/document-preview", status_code=status.HTTP_200_OK)
def preview_tailored_document(
    payload: TailoringDocumentPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    job = db.query(JobDescription).filter(JobDescription.id == payload.job_description_id, JobDescription.user_id == current_user.id).first()
    if not resume or not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume or job description not found")

    service = TailoringService(db)
    finalized = service.finalize(resume, job, payload.accepted_change_ids)
    accepted_changes = finalized.get("accepted_changes", [])
    final_text = finalized.get("final_text") or finalized.get("original_text") or ""

    from app.services.resume_version_service import ResumeVersionService

    renderer = ResumeVersionService(db)
    if payload.format == "docx":
        data = renderer.build_docx_bytes(resume, final_text, accepted_changes)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        extension = "docx"
    else:
        data = renderer.build_pdf_bytes(resume, final_text, accepted_changes)
        media_type = "application/pdf"
        extension = "pdf"

    filename = f"tailored-preview.{extension}"
    return StreamingResponse(
        BytesIO(data),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/finalize", response_model=TailoringFinalizeResponse, status_code=status.HTTP_200_OK)
def finalize_tailoring(
    payload: TailoringFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TailoringFinalizeResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    job = db.query(JobDescription).filter(JobDescription.id == payload.job_description_id, JobDescription.user_id == current_user.id).first()
    if not resume or not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume or job description not found")

    service = TailoringService(db)
    result = service.finalize(resume, job, payload.accepted_change_ids)
    return TailoringFinalizeResponse(**result)


@router.post("/restore", response_model=TailoringRestoreResponse, status_code=status.HTTP_200_OK)
def restore_original_resume(
    payload: TailoringRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TailoringRestoreResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    job = db.query(JobDescription).filter(JobDescription.id == payload.job_description_id, JobDescription.user_id == current_user.id).first()
    if not resume or not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume or job description not found")

    service = TailoringService(db)
    return TailoringRestoreResponse(**service.restore(resume, job))
