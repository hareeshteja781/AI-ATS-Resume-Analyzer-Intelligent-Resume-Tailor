"""persist complete job-match snapshots and enforce one current match per pair

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-24 10:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("""
            DELETE FROM job_match_results older
            USING job_match_results newer
            WHERE older.id < newer.id
              AND older.user_id = newer.user_id
              AND older.resume_id = newer.resume_id
              AND older.job_description_id = newer.job_description_id
        """))

    op.add_column(
        "job_match_results",
        sa.Column("category_scores", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "job_match_results",
        sa.Column("category_statuses", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "job_match_results",
        sa.Column("section_scores", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "job_match_results",
        sa.Column("section_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "job_match_results",
        sa.Column("present_sections", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "job_match_results",
        sa.Column("project_matches", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "job_match_results",
        sa.Column("layout_analysis", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_unique_constraint(
        "uq_job_match_results_user_resume_job",
        "job_match_results",
        ["user_id", "resume_id", "job_description_id"],
    )

    for column in (
        "category_scores", "category_statuses", "section_scores", "section_details",
        "present_sections", "project_matches", "layout_analysis",
    ):
        op.alter_column("job_match_results", column, server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "uq_job_match_results_user_resume_job",
        "job_match_results",
        type_="unique",
    )
    for column in (
        "layout_analysis", "project_matches", "present_sections", "section_details",
        "section_scores", "category_statuses", "category_scores",
    ):
        op.drop_column("job_match_results", column)
