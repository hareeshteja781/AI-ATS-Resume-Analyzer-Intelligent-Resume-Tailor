"""add role and company metadata to job descriptions

Revision ID: 5f1e3d2a4b7c
Revises: 254ef93a7866
Create Date: 2026-09-22 12:15:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "5f1e3d2a4b7c"
down_revision: Union[str, Sequence[str], None] = "254ef93a7866"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("job_descriptions", sa.Column("role_name", sa.String(length=255), nullable=True))
    op.add_column("job_descriptions", sa.Column("company_name", sa.String(length=255), nullable=True))

def downgrade() -> None:
    op.drop_column("job_descriptions", "company_name")
    op.drop_column("job_descriptions", "role_name")
