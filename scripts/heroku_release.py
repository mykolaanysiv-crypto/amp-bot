from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.db import Database
from app.domain_services import bootstrap_defaults
from app.observability import configure_observability


async def legacy_compatibility_bootstrap() -> None:
    settings = get_settings()
    db = Database(settings)
    try:
        # Transitional v1.12 phase: keep the proven idempotent legacy upgrader
        # for pre-v1.12 installations, then let Alembic own new revisions.
        await db.init()
        await bootstrap_defaults(db, settings)
    finally:
        await db.close()


def main() -> None:
    configure_observability(service="release")
    asyncio.run(legacy_compatibility_bootstrap())
    from scripts.alembic_bootstrap import upgrade_head
    upgrade_head()
    from scripts.production_preflight import main as production_preflight
    production_preflight()
    logging.getLogger("amp.release").info("Release bootstrap, Alembic upgrade and production preflight completed")


if __name__ == "__main__":
    main()
