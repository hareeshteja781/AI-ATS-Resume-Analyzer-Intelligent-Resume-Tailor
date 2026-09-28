from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.processing_task import ProcessingTask


class ProcessingTaskService:
    def __init__(self, db: Session):
        self.db = db

    def create_task(
        self,
        *,
        user_id: int,
        task_type: str,
        job_key: str,
        status: str = "queued",
    ) -> ProcessingTask:
        existing = (
            self.db.query(ProcessingTask)
            .filter(ProcessingTask.job_key == job_key)
            .first()
        )
        if existing is not None:
            return existing

        task = ProcessingTask(
            user_id=user_id,
            task_type=task_type,
            job_key=job_key,
            status=status,
            progress=0,
            retryable=False,
            error_message=None,
            result=None,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_task(self, task_id: int) -> ProcessingTask | None:
        return (
            self.db.query(ProcessingTask)
            .filter(ProcessingTask.id == task_id)
            .first()
        )
    def update_progress(self, task_id: int, progress: int) -> ProcessingTask:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        task.progress = max(0, min(100, progress))
        if task.status not in {"completed", "failed"}:
            task.status = "running"
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_running(self, task_id: int) -> ProcessingTask:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        task.status = "running"
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_completed(
        self,
        task_id: int,
        result: dict[str, object] | None = None,
    ) -> ProcessingTask:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        task.status = "completed"
        task.progress = 100
        task.result = result or {}
        task.error_message = None
        task.retryable = False
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_failed(
        self,
        task_id: int,
        error_message: str,
        *,
        retryable: bool = False,
    ) -> ProcessingTask:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        task.status = "failed"
        task.retryable = retryable
        task.error_message = error_message
        task.updated_at = datetime.now(timezone.utc)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task
