from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TailoringChange(Base):
    __tablename__ = "tailoring_changes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    job_description_id: Mapped[int] = mapped_column(ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True)

    original_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_jd_requirement: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    requirement_category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    change_category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    truthfulness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="REQUIRES_REVIEW")
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    user_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, default="RESUME_EDIT")
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("job_match_results.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
