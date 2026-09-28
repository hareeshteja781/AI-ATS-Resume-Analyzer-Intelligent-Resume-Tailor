from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_active_user
from app.db.database import get_db
from app.models.user import User
from app.services.processing_task_service import ProcessingTaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    service = ProcessingTaskService(db)
    task = service.get_task(task_id)
    if task is None or task.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return {
        "id": task.id,
        "user_id": task.user_id,
        "task_type": task.task_type,
        "job_key": task.job_key,
        "status": task.status,
        "progress": task.progress,
        "retryable": task.retryable,
        "error_message": task.error_message,
        "result": task.result,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }
