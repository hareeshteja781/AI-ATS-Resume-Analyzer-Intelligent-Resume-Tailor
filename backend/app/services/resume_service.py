from __future__ import annotations

import logging
import os

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.core.security import get_current_active_user
from app.repositories.resume_repository import ResumeRepository
from app.models.document_chunk import DocumentChunk
from app.models.embedding import Embedding
from app.models.job_match_result import JobMatchResult
from app.models.resume_version import ResumeVersion
from app.models.resume import Resume
from app.services.document_processing import (
    MAX_FILE_SIZE_BYTES,
    extract_text_from_upload,
    validate_document_signature,
    validate_upload,
)
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.services.chunking import chunk_text
from app.services.embedding_service import EmbeddingRepository, EmbeddingService, GeminiEmbeddingProvider
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class ResumeService:
    def __init__(self, db):
        self.db = db
        self.repository = ResumeRepository(db)

    def create_from_upload(self, user_id: int, file: UploadFile) -> dict:
        validate_upload(file)
        file_bytes = file.file.read()
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File is too large. Maximum supported size is 10MB.",
            )

        content_type = file.content_type or "application/octet-stream"
        validate_document_signature(file_bytes, content_type)
        text_content = extract_text_from_upload(file_bytes, content_type)
        original_filename = file.filename or "resume"
        storage = StorageService()
        storage_path = storage.put_upload(
            user_id=user_id,
            kind="resumes",
            filename=original_filename,
            data=file_bytes,
            content_type=content_type,
        )

        resume = None
        try:
            resume = self.repository.create(
                user_id=user_id,
                filename=original_filename,
                original_filename=original_filename,
                content_type=content_type,
                file_size=len(file_bytes),
                storage_path=storage_path,
                text_content=text_content,
                status="processed",
                docx_layout_preserved=content_type.endswith("wordprocessingml.document"),
            )

            chunks = chunk_text(text_content)
            stored_chunks = DocumentChunkRepository(self.db).upsert_chunks(
                resume_id=resume.id,
                chunks=chunks,
            )

            if settings.GEMINI_API_KEY and stored_chunks:
                try:
                    embedding_repo = EmbeddingRepository(self.db)
                    embedding_service = EmbeddingService(
                        repository=embedding_repo,
                        provider=GeminiEmbeddingProvider(),
                        user_id=user_id,
                    )
                    embedding_service.process_chunks(
                        source_type="resume_chunk",
                        source_id=resume.id,
                        document_id=resume.id,
                        chunks=stored_chunks,
                        user_id=user_id,
                    )
                except Exception:
                    logger.exception(
                        "Resume embedding generation failed for user_id=%s resume_id=%s",
                        user_id,
                        resume.id,
                    )
                    resume.status = "failed"
                    resume.processing_error = "Resume embedding generation failed."
                    self.db.add(resume)
                    self.db.commit()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Resume embedding generation failed.",
                    )

            return {
                "id": resume.id,
                "user_id": user_id,
                "filename": resume.filename,
                "original_filename": resume.original_filename,
                "content_type": resume.content_type,
                "file_size": resume.file_size,
                "storage_path": resume.storage_path,
                "text_content": resume.text_content,
                "status": resume.status,
                "processing_error": resume.processing_error,
                "docx_layout_preserved": resume.docx_layout_preserved,
            }
        except Exception:
            if resume is None:
                try:
                    storage.delete(storage_path)
                except Exception:
                    logger.exception("Failed to clean up stored resume object: %s", storage_path)
            raise

    def delete_resume(self, resume_id: int, user_id: int) -> None:
        resume = self.db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == user_id).first()
        if resume is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

        storage = StorageService()
        keys = [resume.storage_path]
        versions = self.db.query(ResumeVersion).filter(ResumeVersion.resume_id == resume.id, ResumeVersion.user_id == user_id).all()
        keys.extend(path for version in versions for path in (version.document_path, version.pdf_path) if path)
        chunk_ids = [row.id for row in self.db.query(DocumentChunk.id).filter(DocumentChunk.resume_id == resume.id).all()]
        if chunk_ids:
            self.db.query(Embedding).filter(Embedding.chunk_id.in_(chunk_ids), Embedding.user_id == user_id).delete(synchronize_session=False)
        self.db.query(JobMatchResult).filter(JobMatchResult.resume_id == resume.id, JobMatchResult.user_id == user_id).delete(synchronize_session=False)
        self.db.query(ResumeVersion).filter(ResumeVersion.resume_id == resume.id, ResumeVersion.user_id == user_id).delete(synchronize_session=False)
        self.db.query(DocumentChunk).filter(DocumentChunk.resume_id == resume.id).delete(synchronize_session=False)
        self.db.delete(resume)
        self.db.commit()
        for key in keys:
            try:
                storage.delete(key)
            except (FileNotFoundError, OSError, ValueError):
                pass

