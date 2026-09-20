"""Add event commitment XP rules and reward bookkeeping.

Revision ID: 20260920_0008
Revises: 20260919_0007
"""
from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260920_0008"
down_revision: Union[str, None] = "20260919_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "events" in tables:
        cols = _columns("events")
        if "preregistration_bonus_xp" not in cols:
            op.add_column("events", sa.Column("preregistration_bonus_xp", sa.Integer(), nullable=False, server_default="5"))
        if "no_show_penalty_xp" not in cols:
            op.add_column("events", sa.Column("no_show_penalty_xp", sa.Integer(), nullable=False, server_default="5"))

    if "event_registrations" in tables:
        cols = _columns("event_registrations")
        if "registration_source" not in cols:
            op.add_column("event_registrations", sa.Column("registration_source", sa.String(length=24), nullable=False, server_default="legacy"))
        if "attendance_xp_awarded" not in cols:
            op.add_column("event_registrations", sa.Column("attendance_xp_awarded", sa.Integer(), nullable=False, server_default="0"))
        if "preregistration_bonus_xp_awarded" not in cols:
            op.add_column("event_registrations", sa.Column("preregistration_bonus_xp_awarded", sa.Integer(), nullable=False, server_default="0"))
        if "no_show_penalty_xp_applied" not in cols:
            op.add_column("event_registrations", sa.Column("no_show_penalty_xp_applied", sa.Integer(), nullable=False, server_default="0"))
        if "volunteer_hours_awarded" not in cols:
            op.add_column("event_registrations", sa.Column("volunteer_hours_awarded", sa.Float(), nullable=False, server_default="0"))

        # Preserve the bookkeeping state for already-confirmed historical attendance.
        # Existing releases stored the actual XP in xp_transactions, so use that as
        # the source of truth rather than assuming the event reward never changed.
        op.execute(sa.text("""
            UPDATE event_registrations
            SET attendance_xp_awarded = COALESCE((
                SELECT SUM(xp_transactions.amount)
                FROM xp_transactions
                WHERE xp_transactions.event_id = event_registrations.event_id
                  AND xp_transactions.user_id = event_registrations.user_id
                  AND xp_transactions.category = 'event'
            ), 0)
            WHERE status = 'attended' AND attendance_xp_awarded = 0
        """))
        op.execute(sa.text("""
            UPDATE event_registrations
            SET volunteer_hours_awarded = COALESCE((
                SELECT events.volunteer_hours FROM events
                WHERE events.id = event_registrations.event_id
            ), 0)
            WHERE status = 'attended' AND volunteer_hours_awarded = 0
        """))


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "event_registrations" in tables:
        cols = _columns("event_registrations")
        for name in (
            "volunteer_hours_awarded",
            "registration_source",
            "no_show_penalty_xp_applied",
            "preregistration_bonus_xp_awarded",
            "attendance_xp_awarded",
        ):
            if name in cols:
                op.drop_column("event_registrations", name)
    if "events" in tables:
        cols = _columns("events")
        for name in ("no_show_penalty_xp", "preregistration_bonus_xp"):
            if name in cols:
                op.drop_column("events", name)
