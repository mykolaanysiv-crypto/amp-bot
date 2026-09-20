"""Privacy & Data Integrity 2.0 data-encryption adoption.

Revision ID: 20260920_0010
Revises: 20260920_0009

No column types are changed: sensitive fields remain TEXT at the PostgreSQL
layer and are transparently encrypted/decrypted by EncryptedText. This revision
backfills existing plaintext rows so data at rest is encrypted immediately.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.field_crypto import decrypt_field, encrypt_field, is_encrypted

revision: str = "20260920_0010"
down_revision: Union[str, None] = "20260920_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SENSITIVE_USER_COLUMNS = (
    "vulnerability_categories",
    "block_reason",
    "deletion_reason",
    "restoration_answers_json",
    "registration_rejection_reason",
)


def _existing_user_columns(bind) -> set[str]:
    return {col["name"] for col in inspect(bind).get_columns("users")}


def upgrade() -> None:
    bind = op.get_bind()
    if "users" not in set(inspect(bind).get_table_names()):
        return
    columns = _existing_user_columns(bind)
    wanted = [name for name in SENSITIVE_USER_COLUMNS if name in columns]
    if not wanted:
        return
    rows = bind.execute(sa.text("SELECT id, " + ", ".join(wanted) + " FROM users")).mappings().all()
    for row in rows:
        changes: dict[str, str] = {}
        for name in wanted:
            value = row.get(name)
            if isinstance(value, str) and value and not is_encrypted(value):
                encrypted = encrypt_field(value)
                if encrypted is not None:
                    changes[name] = encrypted
        if changes:
            assignments = ", ".join(f"{name}=:{name}" for name in changes)
            bind.execute(sa.text(f"UPDATE users SET {assignments} WHERE id=:id"), {"id": row["id"], **changes})


def downgrade() -> None:
    bind = op.get_bind()
    if "users" not in set(inspect(bind).get_table_names()):
        return
    columns = _existing_user_columns(bind)
    wanted = [name for name in SENSITIVE_USER_COLUMNS if name in columns]
    if not wanted:
        return
    rows = bind.execute(sa.text("SELECT id, " + ", ".join(wanted) + " FROM users")).mappings().all()
    for row in rows:
        changes: dict[str, str] = {}
        for name in wanted:
            value = row.get(name)
            if isinstance(value, str) and is_encrypted(value):
                plain = decrypt_field(value)
                if plain is not None:
                    changes[name] = plain
        if changes:
            assignments = ", ".join(f"{name}=:{name}" for name in changes)
            bind.execute(sa.text(f"UPDATE users SET {assignments} WHERE id=:id"), {"id": row["id"], **changes})
