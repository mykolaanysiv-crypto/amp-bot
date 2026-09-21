"""Quick XP challenges.

Revision ID: 20260921_0011
Revises: 20260920_0010
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260921_0011"
down_revision: Union[str, None] = "20260920_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quick_xp_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False, server_default="quiz"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("xp_reward", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("correct_option", sa.Integer(), nullable=True),
        sa.Column("media_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("featured_home", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_by_label", sa.String(length=160), nullable=False, server_default="web"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quick_xp_challenges_kind", "quick_xp_challenges", ["kind"])
    op.create_index("ix_quick_xp_challenges_active", "quick_xp_challenges", ["active"])
    op.create_index("ix_quick_xp_challenges_featured_home", "quick_xp_challenges", ["featured_home"])
    op.create_index("ix_quick_xp_challenges_starts_at", "quick_xp_challenges", ["starts_at"])
    op.create_index("ix_quick_xp_challenges_ends_at", "quick_xp_challenges", ["ends_at"])

    op.create_table(
        "quick_xp_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("challenge_id", sa.Integer(), sa.ForeignKey("quick_xp_challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer_option", sa.Integer(), nullable=True),
        sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("challenge_id", "user_id", name="uq_quick_xp_challenge_user"),
    )
    op.create_index("ix_quick_xp_completions_challenge_id", "quick_xp_completions", ["challenge_id"])
    op.create_index("ix_quick_xp_completions_user_id", "quick_xp_completions", ["user_id"])
    op.create_index("ix_quick_xp_completions_completed_at", "quick_xp_completions", ["completed_at"])


def downgrade() -> None:
    op.drop_table("quick_xp_completions")
    op.drop_table("quick_xp_challenges")
