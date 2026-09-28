from typing import Any

from sqlalchemy.orm import Session

from app.models.job_match_result import JobMatchResult


class JobMatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: int, resume_id: int, job_description_id: int, payload: dict[str, Any]) -> JobMatchResult:
        # A match is the current analysis for one owned resume/JD pair. Update
        # the latest row instead of creating duplicates on every Analyze click.
        result = (
            self.db.query(JobMatchResult)
            .filter(
                JobMatchResult.user_id == user_id,
                JobMatchResult.resume_id == resume_id,
                JobMatchResult.job_description_id == job_description_id,
            )
            .order_by(JobMatchResult.id.desc())
            .first()
        )
        if result is None:
            result = JobMatchResult(
                user_id=user_id,
                resume_id=resume_id,
                job_description_id=job_description_id,
            )
            self.db.add(result)

        for field in (
            "job_match_score", "ats_compatibility_score", "layout_preservation_score",
            "truthfulness_status", "matched_skills", "missing_skills",
            "partially_matched_skills", "responsibilities_matched", "evidence_found",
            "important_gaps", "ats_structure_issues", "recommendations", "score_breakdown",
            "benchmark", "requirement_matches", "category_scores", "category_statuses",
            "section_scores", "section_details", "present_sections", "project_matches",
            "layout_analysis",
        ):
            if field in payload:
                setattr(result, field, payload[field])

        self.db.commit()
        self.db.refresh(result)
        return result
