from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.config import get_settings
from app.db import Database
from app.field_crypto import current_key_id, is_encrypted, reencrypt_field

COLUMNS = (
    "vulnerability_categories",
    "block_reason",
    "deletion_reason",
    "restoration_answers_json",
    "registration_rejection_reason",
)


async def run() -> None:
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    await db.init()
    updated = 0
    try:
        async with db.session_factory() as session:
            rows = (await session.execute(text(
                "SELECT id, " + ", ".join(COLUMNS) + " FROM users"
            ))).mappings().all()
            for row in rows:
                changes: dict[str, str] = {}
                for name in COLUMNS:
                    value = row.get(name)
                    if isinstance(value, str) and value:
                        rotated = reencrypt_field(value)
                        if rotated != value or not is_encrypted(value):
                            if rotated is not None:
                                changes[name] = rotated
                if changes:
                    assignments = ", ".join(f"{name}=:{name}" for name in changes)
                    await session.execute(text(f"UPDATE users SET {assignments} WHERE id=:id"), {"id": row["id"], **changes})
                    updated += 1
            await session.commit()
    finally:
        await db.close()
    print(f"Field encryption rotation complete: key_id={current_key_id()}, users_updated={updated}")


if __name__ == "__main__":
    asyncio.run(run())
