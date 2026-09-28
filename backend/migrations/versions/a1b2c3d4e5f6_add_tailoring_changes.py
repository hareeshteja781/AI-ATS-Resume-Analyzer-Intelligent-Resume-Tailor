"""add persisted tailoring changes

Revision ID: a1b2c3d4e5f6
Revises: 8a6e2f4c9d1b
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8a6e2f4c9d1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tailoring_changes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("job_description_id", sa.Integer(), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("proposed_content", sa.Text(), nullable=False),
        sa.Column("target_jd_requirement", sa.String(length=255), nullable=False),
        sa.Column("requirement_category", sa.String(length=64), nullable=False),
        sa.Column("change_category", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=255), nullable=True),
        sa.Column("truthfulness_status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("user_verified", sa.Boolean(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_description_id"], ["job_descriptions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["job_match_results.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tailoring_changes_user_id", "tailoring_changes", ["user_id"])
    op.create_index("ix_tailoring_changes_resume_id", "tailoring_changes", ["resume_id"])
    op.create_index("ix_tailoring_changes_job_description_id", "tailoring_changes", ["job_description_id"])
    op.create_index("ix_tailoring_changes_analysis_id", "tailoring_changes", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_tailoring_changes_analysis_id", table_name="tailoring_changes")
    op.drop_index("ix_tailoring_changes_job_description_id", table_name="tailoring_changes")
    op.drop_index("ix_tailoring_changes_resume_id", table_name="tailoring_changes")
    op.drop_index("ix_tailoring_changes_user_id", table_name="tailoring_changes")
    op.drop_table("tailoring_changes")
