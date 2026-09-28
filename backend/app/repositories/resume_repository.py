from sqlalchemy.orm import Session

from app.models.resume import Resume


class ResumeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: int, filename: str, original_filename: str, content_type: str, file_size: int, storage_path: str, text_content: str, status: str = "processed", docx_layout_preserved: bool = False) -> Resume:
        resume = Resume(
            user_id=user_id,
            filename=filename,
            original_filename=original_filename,
            content_type=content_type,
            file_size=file_size,
            storage_path=storage_path,
            text_content=text_content,
            status=status,
            docx_layout_preserved=docx_layout_preserved,
        )
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume

    def list_for_user(self, user_id: int) -> list[Resume]:
        return self.db.query(Resume).filter(Resume.user_id == user_id).order_by(Resume.created_at.desc()).all()
