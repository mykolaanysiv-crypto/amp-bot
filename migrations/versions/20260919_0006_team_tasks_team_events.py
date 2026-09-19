"""Add AMP team tasks and restricted team events.

Revision ID: 20260919_0006
Revises: 20260918_0005
"""
from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260919_0006"
down_revision: Union[str, None] = "20260918_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "events" in tables:
        cols = {c["name"] for c in inspector.get_columns("events")}
        if "access_scope" not in cols:
            op.add_column("events", sa.Column("access_scope", sa.String(length=24), nullable=False, server_default="general"))
        indexes = {i["name"] for i in inspect(bind).get_indexes("events")}
        if "ix_events_access_scope" not in indexes:
            op.create_index("ix_events_access_scope", "events", ["access_scope"], unique=False)

    if "team_tasks" not in tables:
        op.create_table(
            "team_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("xp_reward", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("deadline", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="assigned"),
            sa.Column("created_by_label", sa.String(length=160), nullable=False, server_default="web"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("report_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("report_photo_path", sa.String(length=500), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by", sa.String(length=160), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("xp_awarded_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_team_tasks_assignee_user_id", "team_tasks", ["assignee_user_id"], unique=False)
        op.create_index("ix_team_tasks_deadline", "team_tasks", ["deadline"], unique=False)
        op.create_index("ix_team_tasks_status", "team_tasks", ["status"], unique=False)
        op.create_index("ix_team_tasks_created_at", "team_tasks", ["created_at"], unique=False)
        op.create_index("ix_team_tasks_submitted_at", "team_tasks", ["submitted_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "team_tasks" in tables:
        op.drop_table("team_tasks")
    if "events" in tables:
        indexes = {i["name"] for i in inspect(bind).get_indexes("events")}
        if "ix_events_access_scope" in indexes:
            op.drop_index("ix_events_access_scope", table_name="events")
        cols = {c["name"] for c in inspect(bind).get_columns("events")}
        if "access_scope" in cols:
            op.drop_column("events", "access_scope")
