"""Add aggregated participant content views.

Revision ID: 20260915_0002
Revises: 20260915_0001
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260915_0002"
down_revision: Union[str, None] = "20260915_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "content_views" not in tables:
        op.create_table(
            "content_views",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("tg_id", sa.BigInteger(), nullable=False),
            sa.Column("view_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("first_viewed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("last_viewed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("entity_type", "entity_id", "tg_id", name="uq_content_view_entity_tg"),
        )
    existing_indexes = {idx["name"] for idx in inspect(bind).get_indexes("content_views")}
    for name, cols in (
        ("ix_content_views_entity_type", ["entity_type"]),
        ("ix_content_views_entity_id", ["entity_id"]),
        ("ix_content_views_user_id", ["user_id"]),
        ("ix_content_views_tg_id", ["tg_id"]),
        ("ix_content_views_first_viewed_at", ["first_viewed_at"]),
        ("ix_content_views_last_viewed_at", ["last_viewed_at"]),
    ):
        if name not in existing_indexes:
            op.create_index(name, "content_views", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if "content_views" in set(inspect(bind).get_table_names()):
        op.drop_table("content_views")
