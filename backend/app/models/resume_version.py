from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    job_description_id: Mapped[int | None] = mapped_column(ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=True, index=True)

    version_name: Mapped[str] = mapped_column(String(255), nullable=False, default="master")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="master")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    finalization_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tailored_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    final_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    diff_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    document_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    validation_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    truthfulness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUPPORTED")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    resume: Mapped["Resume"] = relationship(back_populates="versions")
    job_description: Mapped["JobDescription"] = relationship()
    user: Mapped["User"] = relationship(back_populates="resume_versions")
