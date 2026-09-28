from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobMatchResult(Base):
    __tablename__ = "job_match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    job_description_id: Mapped[int] = mapped_column(ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True)

    job_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ats_compatibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    layout_preservation_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    truthfulness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUPPORTED")

    matched_skills: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    missing_skills: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    partially_matched_skills: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    responsibilities_matched: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    evidence_found: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    important_gaps: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    ats_structure_issues: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    recommendations: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    score_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    benchmark: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    requirement_matches: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    category_scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    category_statuses: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    section_scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    section_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    present_sections: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    project_matches: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    layout_analysis: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
