from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .field_crypto import decrypt_field, encrypt_field


class EncryptedText(TypeDecorator[str]):
    """Transparent Fernet encryption for sensitive TEXT columns.

    The database type stays TEXT so the change is backward-compatible with the
    existing schema. Existing plaintext is readable during migration and is
    encrypted by migration 20260920_0010 / on subsequent writes.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        return encrypt_field(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        return decrypt_field(value)
