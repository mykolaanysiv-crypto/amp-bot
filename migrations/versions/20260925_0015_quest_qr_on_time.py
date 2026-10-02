"""Add opt-in punctuality quests linked to a specific event.

Revision ID: 20260925_0015
Revises: 20260921_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20260925_0015"
down_revision = "20260921_0014"
branch_labels = None
depends_on = None


# SQLite cannot ALTER TABLE to add a foreign-key constraint. Alembic batch mode
# rebuilds the table only for SQLite, preserving existing rows and indexes.
def _recreate_mode():
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade():
    with op.batch_alter_table("quests", recreate=_recreate_mode()) as batch_op:
        batch_op.add_column(sa.Column("completion_mode", sa.String(24), nullable=False, server_default="manual"))
        batch_op.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("punctuality_grace_minutes", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_foreign_key("fk_quests_event_id_events", "events", ["event_id"], ["id"])
    op.create_index("ix_quests_event_id", "quests", ["event_id"])


def downgrade():
    op.drop_index("ix_quests_event_id", table_name="quests")
    with op.batch_alter_table("quests", recreate=_recreate_mode()) as batch_op:
        batch_op.drop_constraint("fk_quests_event_id_events", type_="foreignkey")
        batch_op.drop_column("punctuality_grace_minutes")
        batch_op.drop_column("event_id")
        batch_op.drop_column("completion_mode")
