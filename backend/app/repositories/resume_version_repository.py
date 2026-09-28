from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.job_description import JobDescription
from app.models.resume_version import ResumeVersion


class ResumeVersionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: int,
        resume_id: int,
        version_name: str,
        source_type: str,
        job_description_id: int | None = None,
        original_text: str = "",
        tailored_text: str = "",
        final_text: str = "",
        diff_text: str = "",
        document_path: str | None = None,
        pdf_path: str | None = None,
        validation_summary: dict | None = None,
        truthfulness_status: str = "SUPPORTED",
        status: str = "draft",
        finalization_status: str = "draft",
        is_master: bool = False,
        is_current: bool = False,
    ) -> ResumeVersion:
        item = ResumeVersion(
            user_id=user_id,
            resume_id=resume_id,
            job_description_id=job_description_id,
            version_name=version_name,
            source_type=source_type,
            status=status,
            finalization_status=finalization_status,
            is_master=is_master,
            is_current=is_current,
            original_text=original_text,
            tailored_text=tailored_text,
            final_text=final_text,
            diff_text=diff_text,
            document_path=document_path,
            pdf_path=pdf_path,
            validation_summary=validation_summary or {},
            truthfulness_status=truthfulness_status,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def get_by_id(self, version_id: int) -> ResumeVersion | None:
        return self.db.query(ResumeVersion).filter(ResumeVersion.id == version_id).first()

    def list_for_resume(self, resume_id: int, user_id: int) -> list[ResumeVersion]:
        return (
            self.db.query(ResumeVersion)
            .filter(ResumeVersion.resume_id == resume_id, ResumeVersion.user_id == user_id)
            .order_by(ResumeVersion.created_at.desc())
            .all()
        )

    def list_history(self, user_id: int, query: str | None = None) -> list[ResumeVersion]:
        q = (
            self.db.query(ResumeVersion)
            .join(JobDescription, ResumeVersion.job_description_id == JobDescription.id)
            .filter(
                ResumeVersion.user_id == user_id,
                ResumeVersion.is_master.is_(False),
                ResumeVersion.job_description_id.is_not(None),
                ResumeVersion.finalization_status != "draft",
            )
        )
        if query:
            pattern = f"%{query.strip().lower()}%"
            q = q.filter(
                or_(
                    func.lower(JobDescription.role_name).like(pattern),
                    func.lower(JobDescription.company_name).like(pattern),
                )
            )
        return q.order_by(ResumeVersion.created_at.desc()).all()

    def get_master(self, resume_id: int, user_id: int) -> ResumeVersion | None:
        return (
            self.db.query(ResumeVersion)
            .filter(ResumeVersion.resume_id == resume_id, ResumeVersion.user_id == user_id, ResumeVersion.is_master.is_(True))
            .first()
        )

    def delete(self, version: ResumeVersion) -> None:
        self.db.delete(version)
        self.db.commit()
