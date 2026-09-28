from fastapi import APIRouter, Depends, HTTPException, status
from celery import Celery
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_active_user
from app.db.database import get_db
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.user import User
from app.repositories.job_match_repository import JobMatchRepository
from app.schemas.analysis import ATSAnalysisRequest, ATSAnalysisResponse, JobMatchRequest, JobMatchResponse
from app.services.job_match_service import JobMatchService
from app.services.ats_parser_service import ATSParserService
from app.services.processing_task_service import ProcessingTaskService

router = APIRouter(prefix="/analysis", tags=["Analysis"])


def _get_owned_inputs(payload: JobMatchRequest, db: Session, user_id: int):
    resume = (
        db.query(Resume)
        .filter(Resume.id == payload.resume_id, Resume.user_id == user_id)
        .first()
    )
    job = (
        db.query(JobDescription)
        .filter(
            JobDescription.id == payload.job_description_id,
            JobDescription.user_id == user_id,
        )
        .first()
    )
    if not resume or not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume or job description not found",
        )
    return resume, job


@router.post("/job-match", response_model=JobMatchResponse, status_code=status.HTTP_200_OK)
def analyze_job_match(
    payload: JobMatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JobMatchResponse:
    resume, job = _get_owned_inputs(payload, db, current_user.id)
    service = JobMatchService(db, JobMatchRepository(db))
    result = service.analyze(resume, job, current_user.id)
    return JobMatchResponse(**result)


@router.post("/job-match/async", status_code=status.HTTP_202_ACCEPTED)
def queue_job_match_analysis(
    payload: JobMatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    resume, job = _get_owned_inputs(payload, db, current_user.id)
    task_service = ProcessingTaskService(db)
    task = task_service.create_task(
        user_id=current_user.id,
        task_type="resume_analysis",
        job_key=f"analysis:{resume.id}:{job.id}",
    )

    if task.status == "completed":
        return {"task_id": task.id, "status": task.status, "progress": task.progress, "result": task.result}

    celery_app = Celery(
        "resume_ats_api",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )
    try:
        celery_app.send_task(
            "resume_ats.analyze_job_match",
            args=[task.id, current_user.id, resume.id, job.id],
        )
    except Exception as exc:
        task_service.mark_failed(task.id, str(exc), retryable=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background analysis queue is unavailable.",
        ) from exc

    return {
        "task_id": task.id,
        "status": "queued",
        "progress": task.progress,
        "result": None,
    }


@router.post("/ats", response_model=ATSAnalysisResponse, status_code=status.HTTP_200_OK)
def analyze_ats_compatibility(
    payload: ATSAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ATSAnalysisResponse:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    try:
        result = ATSParserService().analyze_resume(resume, payload.profile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ATSAnalysisResponse(**result)


@router.post("/ats/parser-preview", response_model=ATSAnalysisResponse, status_code=status.HTTP_200_OK)
def preview_ats_parser(
    payload: ATSAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ATSAnalysisResponse:
    return analyze_ats_compatibility(payload, db, current_user)
