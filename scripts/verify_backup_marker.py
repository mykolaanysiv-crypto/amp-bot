from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.db import Database
from app.reliability import backup_verification_status


async def _main() -> int:
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    try:
        async with db.session_factory() as session:
            status = await backup_verification_status(session)
    finally:
        await db.close()
    print(status)
    return 0 if status.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
