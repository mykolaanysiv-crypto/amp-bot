"""v1.20.1 visual experience and web user profiles.

Revision ID: 20261010_0018
Revises: 20261008_0017
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261010_0018"
down_revision: Union[str, None] = "20261008_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("web_staff_accounts") as batch:
        batch.add_column(sa.Column("profile_title", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("profile_bio", sa.Text(), nullable=True))
        batch.add_column(sa.Column("profile_email", sa.Text(), nullable=True))
        batch.add_column(sa.Column("profile_phone", sa.Text(), nullable=True))
        batch.add_column(sa.Column("avatar_path", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("linked_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_web_staff_accounts_linked_user", "users", ["linked_user_id"], ["id"])
        batch.create_index("ix_web_staff_accounts_linked_user_id", ["linked_user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("web_staff_accounts") as batch:
        batch.drop_index("ix_web_staff_accounts_linked_user_id")
        batch.drop_constraint("fk_web_staff_accounts_linked_user", type_="foreignkey")
        batch.drop_column("linked_user_id")
        batch.drop_column("avatar_path")
        batch.drop_column("profile_phone")
        batch.drop_column("profile_email")
        batch.drop_column("profile_bio")
        batch.drop_column("profile_title")
