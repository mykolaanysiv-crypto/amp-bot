import asyncio

from app.config import get_settings
from app.db import Database
from app.services import bootstrap_defaults


async def main() -> None:
    settings = get_settings()
    db = Database(settings)
    try:
        await db.init()
        await bootstrap_defaults(db, settings)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
