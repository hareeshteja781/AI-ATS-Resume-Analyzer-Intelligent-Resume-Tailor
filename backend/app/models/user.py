from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    resumes: Mapped[list["Resume"]] = relationship(back_populates="user")
    job_descriptions: Mapped[list["JobDescription"]] = relationship(back_populates="user")
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(back_populates="user")
    embeddings: Mapped[list["Embedding"]] = relationship(back_populates="user")