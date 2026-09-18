"""Add ambassador responsibility and reports.

Revision ID: 20260917_0003
Revises: 20260915_0002
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260917_0003"
down_revision: Union[str, None] = "20260915_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "ambassador_responsibility" not in cols:
            op.add_column("users", sa.Column("ambassador_responsibility", sa.String(length=64), nullable=True))
        indexes = {i["name"] for i in inspect(bind).get_indexes("users")}
        if "ix_users_ambassador_responsibility" not in indexes:
            op.create_index("ix_users_ambassador_responsibility", "users", ["ambassador_responsibility"], unique=False)
    if "ambassador_reports" not in tables:
        op.create_table(
            "ambassador_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("photo_path", sa.String(length=500), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="submitted"),
            sa.Column("admin_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        )
        op.create_index("ix_ambassador_reports_user_id", "ambassador_reports", ["user_id"])
        op.create_index("ix_ambassador_reports_period_start", "ambassador_reports", ["period_start"])
        op.create_index("ix_ambassador_reports_period_end", "ambassador_reports", ["period_end"])
        op.create_index("ix_ambassador_reports_status", "ambassador_reports", ["status"])
        op.create_index("ix_ambassador_reports_created_at", "ambassador_reports", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "ambassador_reports" in tables:
        op.drop_table("ambassador_reports")
    if "users" in tables:
        cols = {c["name"] for c in inspect(bind).get_columns("users")}
        if "ambassador_responsibility" in cols:
            op.drop_column("users", "ambassador_responsibility")
