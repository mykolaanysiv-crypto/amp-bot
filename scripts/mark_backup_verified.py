from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db import Database
from app.reliability import record_backup_marker


async def _main(label: str) -> None:
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    try:
        await db.init()
        await record_backup_marker(db, label=label)
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record a successfully verified external database backup.")
    parser.add_argument("label", nargs="?", default="Heroku Postgres backup verified")
    args = parser.parse_args()
    asyncio.run(_main(args.label))
