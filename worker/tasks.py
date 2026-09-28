from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Any

backend_path = Path(__file__).resolve().parents[1] / "backend"
project_path = Path(__file__).resolve().parents[1]
for path in (backend_path, project_path):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.db.database import SessionLocal
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.models.processing_task import ProcessingTask
from app.repositories.job_match_repository import JobMatchRepository
from app.services.job_match_service import JobMatchService
from app.services.processing_task_service import ProcessingTaskService
from app.services.resume_version_service import ResumeVersionService
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _execute(task_id: int, operation) -> dict[str, Any]:
    db = SessionLocal()
    task_service = ProcessingTaskService(db)
    try:
        task_service.mark_running(task_id)
        result = operation(db, task_service)
        task_service.mark_completed(task_id, result)
        return result
    except Exception as exc:
        logger.exception("Background task failed: task_id=%s", task_id)
        task_service.mark_failed(task_id, "Background processing failed.", retryable=True)
        raise
    finally:
        db.close()


def _verify_task_owner(db, task_id: int, user_id: int) -> None:
    task = db.query(ProcessingTask).filter(ProcessingTask.id == task_id).first()
    if task is None or task.user_id != user_id:
        raise ValueError("Processing task not found")


def _get_version(db, version_id: int, user_id: int) -> ResumeVersion:
    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.id == version_id, ResumeVersion.user_id == user_id)
        .first()
    )
    if version is None:
        raise ValueError("Resume version not found")
    return version
@celery_app.task(bind=True, name="resume_ats.analyze_job_match", max_retries=2)
def analyze_job_match_task(
    self,
    task_id: int,
    user_id: int,
    resume_id: int,
    job_description_id: int,
):
    def operation(db, task_service):
        _verify_task_owner(db, task_id, user_id)
        task_service.update_progress(task_id, 20)
        resume = (
            db.query(Resume)
            .filter(Resume.id == resume_id, Resume.user_id == user_id)
            .first()
        )
        job = (
            db.query(JobDescription)
            .filter(
                JobDescription.id == job_description_id,
                JobDescription.user_id == user_id,
            )
            .first()
        )
        if resume is None or job is None:
            raise ValueError("Resume or job description not found")

        task_service.update_progress(task_id, 45)
        result = JobMatchService(
            db,
            JobMatchRepository(db),
        ).analyze(resume, job, user_id)
        task_service.update_progress(task_id, 90)
        return result

    try:
        return _execute(task_id, operation)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(
            exc=exc,
            countdown=2 ** (self.request.retries + 1),
        )


@celery_app.task(bind=True, name="resume_ats.generate_docx", max_retries=2)
def generate_docx_task(self, task_id: int, user_id: int, version_id: int):
    def operation(db, task_service):
        _verify_task_owner(db, task_id, user_id)
        task_service.update_progress(task_id, 20)
        version = _get_version(db, version_id, user_id)
        task_service.update_progress(task_id, 50)
        path = ResumeVersionService(db).generate_docx(version)
        task_service.update_progress(task_id, 90)
        return {"document_path": path}

    try:
        return _execute(task_id, operation)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(
            exc=exc,
            countdown=2 ** (self.request.retries + 1),
        )
@celery_app.task(bind=True, name="resume_ats.generate_pdf", max_retries=2)
def generate_pdf_task(self, task_id: int, user_id: int, version_id: int):
    def operation(db, task_service):
        _verify_task_owner(db, task_id, user_id)
        task_service.update_progress(task_id, 20)
        version = _get_version(db, version_id, user_id)
        task_service.update_progress(task_id, 50)
        path = ResumeVersionService(db).generate_pdf(version)
        task_service.update_progress(task_id, 90)
        return {"pdf_path": path}

    try:
        return _execute(task_id, operation)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(
            exc=exc,
            countdown=2 ** (self.request.retries + 1),
        )
