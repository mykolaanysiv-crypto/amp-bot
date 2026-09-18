"""Add targeted survey audiences.

Revision ID: 20260918_0004
Revises: 20260917_0003
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260918_0004"
down_revision: Union[str, None] = "20260917_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "surveys" in tables:
        cols = {c["name"] for c in inspector.get_columns("surveys")}
        if "audience_type" not in cols:
            op.add_column("surveys", sa.Column("audience_type", sa.String(length=24), nullable=False, server_default="all"))
        if "audience_event_id" not in cols:
            op.add_column("surveys", sa.Column("audience_event_id", sa.Integer(), nullable=True))
            op.create_foreign_key("fk_surveys_audience_event_id_events", "surveys", "events", ["audience_event_id"], ["id"])
        indexes = {i["name"] for i in inspect(bind).get_indexes("surveys")}
        if "ix_surveys_audience_type" not in indexes:
            op.create_index("ix_surveys_audience_type", "surveys", ["audience_type"], unique=False)
        if "ix_surveys_audience_event_id" not in indexes:
            op.create_index("ix_surveys_audience_event_id", "surveys", ["audience_event_id"], unique=False)
    if "survey_audience_users" not in tables:
        op.create_table(
            "survey_audience_users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("survey_id", sa.Integer(), sa.ForeignKey("surveys.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("survey_id", "user_id", name="uq_survey_audience_user"),
        )
        op.create_index("ix_survey_audience_users_survey_id", "survey_audience_users", ["survey_id"])
        op.create_index("ix_survey_audience_users_user_id", "survey_audience_users", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "survey_audience_users" in tables:
        op.drop_table("survey_audience_users")
    if "surveys" in tables:
        cols = {c["name"] for c in inspect(bind).get_columns("surveys")}
        if "audience_event_id" in cols:
            op.drop_constraint("fk_surveys_audience_event_id_events", "surveys", type_="foreignkey")
            op.drop_column("surveys", "audience_event_id")
        if "audience_type" in cols:
            op.drop_column("surveys", "audience_type")
