from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    job_description_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_descriptions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)

    content_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    resume: Mapped["Resume | None"] = relationship(back_populates="chunks")
    job_description: Mapped["JobDescription | None"] = relationship(back_populates="chunks")
    embedding: Mapped["Embedding | None"] = relationship(
        back_populates="chunk",
        uselist=False,
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            """
            (
                resume_id IS NOT NULL
                AND job_description_id IS NULL
            )
            OR
            (
                resume_id IS NULL
                AND job_description_id IS NOT NULL
            )
            """,
            name="ck_document_chunks_exactly_one_parent",
        ),
        UniqueConstraint(
            "resume_id",
            "chunk_index",
            name="uq_document_chunks_resume_index",
        ),
        UniqueConstraint(
            "job_description_id",
            "chunk_index",
            name="uq_document_chunks_jd_index",
        ),
        Index(
            "ix_document_chunks_resume_index",
            "resume_id",
            "chunk_index",
        ),
        Index(
            "ix_document_chunks_jd_index",
            "job_description_id",
            "chunk_index",
        ),
    )