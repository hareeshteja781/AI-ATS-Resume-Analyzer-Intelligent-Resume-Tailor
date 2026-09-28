from sqlalchemy.orm import Session

from app.models.job_description import JobDescription


class JobDescriptionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: int, source_type: str, text_content: str, normalized_text: str, filename: str | None = None, role_name: str | None = None, company_name: str | None = None, content_type: str | None = None, file_size: int | None = None, storage_path: str | None = None, url: str | None = None, source_html: str | None = None, prompt_injection_detected: bool = False, status: str = "processed") -> JobDescription:
        instance = JobDescription(
            user_id=user_id,
            filename=filename,
            role_name=role_name,
            company_name=company_name,
            source_type=source_type,
            content_type=content_type,
            file_size=file_size,
            storage_path=storage_path,
            text_content=text_content,
            normalized_text=normalized_text,
            url=url,
            source_html=source_html,
            prompt_injection_detected=prompt_injection_detected,
            status=status,
        )
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def get_for_user(self, job_description_id: int, user_id: int) -> JobDescription | None:
        return (
            self.db.query(JobDescription)
            .filter(
                JobDescription.id == job_description_id,
                JobDescription.user_id == user_id,
            )
            .first()
        )

    def list_for_user(self, user_id: int) -> list[JobDescription]:
        return self.db.query(JobDescription).filter(JobDescription.user_id == user_id).order_by(JobDescription.created_at.desc()).all()
