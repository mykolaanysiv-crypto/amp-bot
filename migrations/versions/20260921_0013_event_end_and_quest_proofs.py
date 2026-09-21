"""Event end time and quest proof photos.

Revision ID: 20260921_0013
Revises: 20260921_0012
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import timedelta

revision: str = "20260921_0013"
down_revision: Union[str, None] = "20260921_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("ends_at", sa.DateTime(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, starts_at FROM events WHERE ends_at IS NULL")).fetchall()
    for row in rows:
        if row.starts_at is not None:
            bind.execute(sa.text("UPDATE events SET ends_at = :ends_at WHERE id = :id"), {"ends_at": row.starts_at + timedelta(hours=2), "id": row.id})
    op.create_index("ix_events_ends_at", "events", ["ends_at"])
    op.add_column("quest_participations", sa.Column("proof_photo_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("quest_participations", "proof_photo_path")
    op.drop_index("ix_events_ends_at", table_name="events")
    op.drop_column("events", "ends_at")
