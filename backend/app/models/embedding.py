from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError as exc:  # pragma: no cover - fail loudly in production, not silently
    raise RuntimeError(
        "pgvector is required for the production embedding model. "
        "Install the PostgreSQL pgvector extension and the Python pgvector package before starting the app."
    ) from exc


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, default="gemini-embedding-001")
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    payload_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="embeddings")
    chunk: Mapped["DocumentChunk"] = relationship(back_populates="embedding")

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "embedding_model",
            "embedding_version",
            name="uq_embeddings_chunk_model_version",
        ),
    )
