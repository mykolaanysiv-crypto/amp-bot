"""v1.19.1 media storage abstraction and lifecycle metadata.

Revision ID: 20261008_0017
Revises: 20261007_0016
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261008_0017"
down_revision: Union[str, None] = "20261007_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column("data", existing_type=sa.LargeBinary(), nullable=True)
        batch.add_column(sa.Column("detected_mime", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("checksum_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("storage_backend", sa.String(length=16), nullable=False, server_default="database"))
        batch.add_column(sa.Column("storage_key", sa.String(length=700), nullable=True))
        batch.add_column(sa.Column("migration_key", sa.String(length=700), nullable=True))
        batch.add_column(sa.Column("lifecycle_state", sa.String(length=24), nullable=False, server_default="active"))
        batch.add_column(sa.Column("integrity_status", sa.String(length=32), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("quarantined_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_verified_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_media_assets_checksum_sha256", ["checksum_sha256"], unique=False)
        batch.create_index("ix_media_assets_storage_backend", ["storage_backend"], unique=False)
        batch.create_index("ix_media_assets_lifecycle_state", ["lifecycle_state"], unique=False)
        batch.create_index("ix_media_assets_integrity_status", ["integrity_status"], unique=False)

    # Existing rows are canonical database-backed assets. Metadata is populated lazily
    # by the integrity scanner/migration tooling; no media bytes move in this migration.
    op.execute("UPDATE media_assets SET storage_backend='database' WHERE storage_backend IS NULL OR storage_backend='' ")


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_index("ix_media_assets_integrity_status")
        batch.drop_index("ix_media_assets_lifecycle_state")
        batch.drop_index("ix_media_assets_storage_backend")
        batch.drop_index("ix_media_assets_checksum_sha256")
        batch.drop_column("last_verified_at")
        batch.drop_column("quarantined_at")
        batch.drop_column("reviewed_at")
        batch.drop_column("integrity_status")
        batch.drop_column("lifecycle_state")
        batch.drop_column("migration_key")
        batch.drop_column("storage_key")
        batch.drop_column("storage_backend")
        batch.drop_column("checksum_sha256")
        batch.drop_column("detected_mime")
        batch.alter_column("data", existing_type=sa.LargeBinary(), nullable=False)
