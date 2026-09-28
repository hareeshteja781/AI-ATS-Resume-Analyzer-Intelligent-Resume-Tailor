"""add source HTML for URL job descriptions and merge alembic heads

Revision ID: 8a6e2f4c9d1b
Revises: e5775f16b253, 5f1e3d2a4b7c
Create Date: 2026-09-22 13:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a6e2f4c9d1b"
down_revision: Union[str, Sequence[str], None] = (
    "e5775f16b253",
    "5f1e3d2a4b7c",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "job_descriptions",
        sa.Column("source_html", sa.Text(), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("job_descriptions", "source_html")
