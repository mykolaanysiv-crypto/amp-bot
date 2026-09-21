"""Quick XP multi-question quizzes and per-question scoring.

Revision ID: 20260921_0012
Revises: 20260921_0011
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260921_0012"
down_revision: Union[str, None] = "20260921_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quick_xp_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("challenge_id", sa.Integer(), sa.ForeignKey("quick_xp_challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("correct_option", sa.Integer(), nullable=False),
        sa.Column("xp_reward", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quick_xp_questions_challenge_id", "quick_xp_questions", ["challenge_id"])

    op.create_table(
        "quick_xp_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("challenge_id", sa.Integer(), sa.ForeignKey("quick_xp_challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("quick_xp_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answer_option", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answered_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("question_id", "user_id", name="uq_quick_xp_question_user"),
    )
    op.create_index("ix_quick_xp_answers_challenge_id", "quick_xp_answers", ["challenge_id"])
    op.create_index("ix_quick_xp_answers_question_id", "quick_xp_answers", ["question_id"])
    op.create_index("ix_quick_xp_answers_user_id", "quick_xp_answers", ["user_id"])
    op.create_index("ix_quick_xp_answers_answered_at", "quick_xp_answers", ["answered_at"])

    # Preserve existing one-question mini quizzes by promoting the legacy fields
    # into the new question table. Other Quick XP types keep using the legacy
    # challenge-level question/options fields by design.
    op.execute(sa.text("""
        INSERT INTO quick_xp_questions
            (challenge_id, text, options_json, correct_option, xp_reward, sort_order, created_at)
        SELECT id, question, options_json, correct_option,
               CASE WHEN xp_reward < 1 THEN 1 ELSE xp_reward END,
               10, created_at
        FROM quick_xp_challenges
        WHERE kind = 'quiz'
          AND COALESCE(TRIM(question), '') <> ''
          AND correct_option IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_table("quick_xp_answers")
    op.drop_table("quick_xp_questions")
