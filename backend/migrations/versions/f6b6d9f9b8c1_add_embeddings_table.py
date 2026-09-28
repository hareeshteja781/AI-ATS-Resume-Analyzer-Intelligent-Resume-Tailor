"""add embeddings table

Revision ID: f6b6d9f9b8c1
Revises: e64d1c9c7e5a
Create Date: 2026-09-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "f6b6d9f9b8c1"
down_revision: Union[str, Sequence[str], None] = "e64d1c9c7e5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("embedding_model", sa.String(length=128), nullable=False, server_default="gemini-embedding-001"),
        sa.Column("embedding_version", sa.String(length=64), nullable=False, server_default="v1"),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_embeddings_user_id"), "embeddings", ["user_id"], unique=False)
    op.create_index(op.f("ix_embeddings_source_type"), "embeddings", ["source_type"], unique=False)
    op.create_index(op.f("ix_embeddings_source_id"), "embeddings", ["source_id"], unique=False)
    op.create_index(op.f("ix_embeddings_content_hash"), "embeddings", ["content_hash"], unique=False)
    op.create_index(op.f("ix_embeddings_document_id"), "embeddings", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_embeddings_document_id"), table_name="embeddings")
    op.drop_index(op.f("ix_embeddings_content_hash"), table_name="embeddings")
    op.drop_index(op.f("ix_embeddings_source_id"), table_name="embeddings")
    op.drop_index(op.f("ix_embeddings_source_type"), table_name="embeddings")
    op.drop_index(op.f("ix_embeddings_user_id"), table_name="embeddings")
    op.drop_table("embeddings")
