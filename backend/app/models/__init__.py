from app.db.base import Base
from app.models.embedding import Embedding
from app.models.job_description import JobDescription
from app.models.job_match_result import JobMatchResult
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.models.user import User
from app.models.document_chunk import DocumentChunk
from app.models.processing_task import ProcessingTask
from app.models.tailoring_change import TailoringChange

__all__ = [
    "Base",
    "Embedding",
    "JobDescription",
    "JobMatchResult",
    "Resume",
    "ResumeVersion",
    "User",
    "DocumentChunk",
    "ProcessingTask",
    "TailoringChange",
]
