from __future__ import annotations

import sys
from pathlib import Path

backend_path = Path(__file__).resolve().parents[1] / "backend"
project_path = Path(__file__).resolve().parents[1]
for path in (backend_path, project_path):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "resume_ats_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="resume_ats.health")
def health_check() -> str:
    return "ok"


from worker import tasks as _worker_tasks  # noqa: E402,F401
