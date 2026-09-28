from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.services.chunking import TextChunk


class DocumentChunkRepository:
    def __init__(self, db: Session):
        self.db = db

    def _parent_query(self, *, resume_id: int | None, job_description_id: int | None):
        if (resume_id is None) == (job_description_id is None):
            raise ValueError("Exactly one parent must be provided.")
        query = self.db.query(DocumentChunk)
        if resume_id is not None:
            return query.filter(DocumentChunk.resume_id == resume_id)
        return query.filter(DocumentChunk.job_description_id == job_description_id)

    def upsert_chunks(
        self,
        *,
        chunks: list[TextChunk],
        resume_id: int | None = None,
        job_description_id: int | None = None,
    ) -> list[DocumentChunk]:
        existing = self._parent_query(
            resume_id=resume_id,
            job_description_id=job_description_id,
        ).all()
        by_index = {chunk.chunk_index: chunk for chunk in existing}

        for item in chunks:
            current = by_index.get(item.index)
            if current is None:
                current = DocumentChunk(
                    resume_id=resume_id,
                    job_description_id=job_description_id,
                    chunk_index=item.index,
                    text=item.text,
                    content_hash=item.content_hash,
                    char_start=item.char_start,
                    char_end=item.char_end,
                )
                self.db.add(current)
            else:
                current.text = item.text
                current.content_hash = item.content_hash
                current.char_start = item.char_start
                current.char_end = item.char_end
        wanted = {item.index for item in chunks}
        for current in existing:
            if current.chunk_index not in wanted:
                self.db.delete(current)

        self.db.flush()
        rows = self._parent_query(
            resume_id=resume_id,
            job_description_id=job_description_id,
        ).order_by(DocumentChunk.chunk_index).all()
        self.db.commit()
        return rows
