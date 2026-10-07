"""v1.19.0 security and observability: staff passkeys.

Revision ID: 20261007_0016
Revises: 20260925_0015
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261007_0016"
down_revision: Union[str, None] = "20260925_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_authn_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("web_staff_accounts.id"), nullable=False),
        sa.Column("credential_id_b64", sa.String(length=1024), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("device_type", sa.String(length=48), nullable=False, server_default=""),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transports_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="Passkey"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_web_authn_credentials_account_id", "web_authn_credentials", ["account_id"])
    # Mirrors mapped_column(unique=True, index=True): one unique index, not a
    # redundant UniqueConstraint plus a non-unique index.
    op.create_index("ix_web_authn_credentials_credential_id_b64", "web_authn_credentials", ["credential_id_b64"], unique=True)
    op.create_index("ix_web_authn_credentials_last_used_at", "web_authn_credentials", ["last_used_at"])
    op.create_index("ix_web_authn_credentials_revoked_at", "web_authn_credentials", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_web_authn_credentials_revoked_at", table_name="web_authn_credentials")
    op.drop_index("ix_web_authn_credentials_last_used_at", table_name="web_authn_credentials")
    op.drop_index("ix_web_authn_credentials_credential_id_b64", table_name="web_authn_credentials")
    op.drop_index("ix_web_authn_credentials_account_id", table_name="web_authn_credentials")
    op.drop_table("web_authn_credentials")
