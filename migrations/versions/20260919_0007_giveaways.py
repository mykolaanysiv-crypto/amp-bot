"""Add configurable giveaways, prizes, entries and winners.

Revision ID: 20260919_0007
Revises: 20260919_0006
"""
from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260919_0007"
down_revision: Union[str, None] = "20260919_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "giveaways" not in tables:
        op.create_table(
            "giveaways",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("participation_mode", sa.String(length=24), nullable=False, server_default="automatic"),
            sa.Column("task_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("audience_type", sa.String(length=24), nullable=False, server_default="all"),
            sa.Column("audience_value", sa.Text(), nullable=False, server_default=""),
            sa.Column("starts_at", sa.DateTime(), nullable=True),
            sa.Column("ends_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
            sa.Column("created_by_label", sa.String(length=160), nullable=False, server_default="web"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("drawn_at", sa.DateTime(), nullable=True),
            sa.Column("draw_seed", sa.String(length=128), nullable=True),
            sa.Column("draw_algorithm", sa.String(length=64), nullable=True),
        )
        op.create_index("ix_giveaways_participation_mode", "giveaways", ["participation_mode"], unique=False)
        op.create_index("ix_giveaways_audience_type", "giveaways", ["audience_type"], unique=False)
        op.create_index("ix_giveaways_starts_at", "giveaways", ["starts_at"], unique=False)
        op.create_index("ix_giveaways_ends_at", "giveaways", ["ends_at"], unique=False)
        op.create_index("ix_giveaways_status", "giveaways", ["status"], unique=False)
        op.create_index("ix_giveaways_created_at", "giveaways", ["created_at"], unique=False)
        op.create_index("ix_giveaways_drawn_at", "giveaways", ["drawn_at"], unique=False)

    if "giveaway_prizes" not in tables:
        op.create_table(
            "giveaway_prizes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("giveaway_id", sa.Integer(), sa.ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("image_path", sa.String(length=500), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_giveaway_prizes_giveaway_id", "giveaway_prizes", ["giveaway_id"], unique=False)

    if "giveaway_entries" not in tables:
        op.create_table(
            "giveaway_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("giveaway_id", sa.Integer(), sa.ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("source", sa.String(length=24), nullable=False, server_default="task"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("report_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("proof_photo_path", sa.String(length=500), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by", sa.String(length=160), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("giveaway_id", "user_id", name="uq_giveaway_entry_user"),
        )
        op.create_index("ix_giveaway_entries_giveaway_id", "giveaway_entries", ["giveaway_id"], unique=False)
        op.create_index("ix_giveaway_entries_user_id", "giveaway_entries", ["user_id"], unique=False)
        op.create_index("ix_giveaway_entries_status", "giveaway_entries", ["status"], unique=False)
        op.create_index("ix_giveaway_entries_submitted_at", "giveaway_entries", ["submitted_at"], unique=False)

    if "giveaway_winners" not in tables:
        op.create_table(
            "giveaway_winners",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("giveaway_id", sa.Integer(), sa.ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prize_id", sa.Integer(), sa.ForeignKey("giveaway_prizes.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("draw_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("notified_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("giveaway_id", "user_id", name="uq_giveaway_winner_user"),
            sa.UniqueConstraint("giveaway_id", "draw_order", name="uq_giveaway_draw_order"),
        )
        op.create_index("ix_giveaway_winners_giveaway_id", "giveaway_winners", ["giveaway_id"], unique=False)
        op.create_index("ix_giveaway_winners_prize_id", "giveaway_winners", ["prize_id"], unique=False)
        op.create_index("ix_giveaway_winners_user_id", "giveaway_winners", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "giveaway_winners" in tables:
        op.drop_table("giveaway_winners")
    if "giveaway_entries" in tables:
        op.drop_table("giveaway_entries")
    if "giveaway_prizes" in tables:
        op.drop_table("giveaway_prizes")
    if "giveaways" in tables:
        op.drop_table("giveaways")
