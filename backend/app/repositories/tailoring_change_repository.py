from sqlalchemy.orm import Session

from app.models.tailoring_change import TailoringChange


class TailoringChangeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, change_id: str, user_id: int) -> TailoringChange | None:
        return (
            self.db.query(TailoringChange)
            .filter(TailoringChange.id == change_id, TailoringChange.user_id == user_id)
            .first()
        )

    def list_for_context(self, user_id: int, resume_id: int, job_description_id: int) -> list[TailoringChange]:
        return (
            self.db.query(TailoringChange)
            .filter(
                TailoringChange.user_id == user_id,
                TailoringChange.resume_id == resume_id,
                TailoringChange.job_description_id == job_description_id,
            )
            .order_by(TailoringChange.created_at.asc())
            .all()
        )

    def upsert(self, *, user_id: int, resume_id: int, job_description_id: int, payload: dict, analysis_id: int | None = None) -> TailoringChange:
        item = self.get(payload["id"], user_id)
        if item is None:
            item = TailoringChange(
                id=payload["id"],
                user_id=user_id,
                resume_id=resume_id,
                job_description_id=job_description_id,
            )
            self.db.add(item)
        for key in (
            "original_content", "proposed_content", "target_jd_requirement", "requirement_category",
            "change_category", "reason", "evidence", "evidence_reference", "truthfulness_status",
            "action_type", "suggested_action",
        ):
            if key in payload:
                setattr(item, key, payload[key])
        if analysis_id is not None:
            item.analysis_id = analysis_id
        self.db.flush()
        return item

    def commit(self) -> None:
        self.db.commit()
        self.db.flush()
