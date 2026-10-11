"""Account-scoped read receipts for web notifications.

Revision ID: 20261011_0019
Revises: 20261010_0018
"""
from alembic import op
import sqlalchemy as sa
revision = "20261011_0019"
down_revision = "20261010_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("web_notification_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("web_staff_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "notification_id", name="uq_web_notification_read"))
    op.create_index("ix_web_notification_reads_account_id", "web_notification_reads", ["account_id"])
    op.create_index("ix_web_notification_reads_notification_id", "web_notification_reads", ["notification_id"])


def downgrade():
    op.drop_index("ix_web_notification_reads_notification_id", table_name="web_notification_reads")
    op.drop_index("ix_web_notification_reads_account_id", table_name="web_notification_reads")
    op.drop_table("web_notification_reads")
