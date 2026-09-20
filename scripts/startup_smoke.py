from __future__ import annotations

"""Production lifecycle smoke for AMP production releases (v1.13.0 factory-aware).

This script deliberately executes the same critical sequence used during a
release:

    Alembic upgrade head -> db.init() -> bootstrap_defaults() -> FastAPI lifespan

Schema migrations MUST run before runtime DB initialization/bootstrap. v1.17.1
removes all schema mutation from ``Database.init()``: Alembic is now the only
production schema authority. The sequence remains safe for production data:
Alembic only moves forward, db.init() performs connectivity/runtime PRAGMAs only,
bootstrap defaults are idempotent, and AMP_STARTUP_SMOKE disables participant-
facing startup broadcasts and long-running background tasks while the real web
lifespan is entered.
"""

import asyncio
import importlib
import logging
import os
from contextlib import contextmanager

from app.config import get_settings
from app.db import Database
from app.domain_services import bootstrap_defaults
from app.observability import configure_observability

log = logging.getLogger("amp.startup_smoke")


@contextmanager
def _smoke_environment():
    previous = os.environ.get("AMP_STARTUP_SMOKE")
    os.environ["AMP_STARTUP_SMOKE"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AMP_STARTUP_SMOKE", None)
        else:
            os.environ["AMP_STARTUP_SMOKE"] = previous


async def _db_init_phase() -> None:
    """Verify runtime DB connectivity after Alembic has applied the schema."""
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    try:
        await db.init()
    finally:
        await db.close()


async def _bootstrap_defaults_phase() -> None:
    """Seed/query defaults only after Alembic has upgraded the mapped schema."""
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    try:
        await bootstrap_defaults(db, settings)
    finally:
        await db.close()


async def _web_startup_phase() -> None:
    # Import only after Alembic so web objects are created against the schema
    # the release will actually expose. v1.17.1 uses the canonical factory only;
    # the transitional app.web.app facade has been retired.
    factory_module = importlib.import_module("app.web.factory")
    app = factory_module.create_app()
    async with app.router.lifespan_context(app):
        if not bool(getattr(app.state, "startup_complete", False)):
            raise RuntimeError("FastAPI lifespan entered without startup_complete")
        # Import the worker module too. This catches refactor/import regressions
        # before production even though Telegram polling is intentionally not
        # started in a release dyno.
        importlib.import_module("app.main")


def run() -> None:
    # v1.17.1: Alembic is the single schema authority. Runtime DB init must never
    # create/alter schema, so migrate first, then verify connectivity and seed.
    from scripts.alembic_bootstrap import upgrade_head
    upgrade_head()

    asyncio.run(_db_init_phase())
    asyncio.run(_bootstrap_defaults_phase())

    with _smoke_environment():
        asyncio.run(_web_startup_phase())

    log.info("Production lifecycle smoke PASS: Alembic -> db.init -> bootstrap -> web lifespan")


def main() -> None:
    if not logging.getLogger().handlers:
        configure_observability(service="startup-smoke")
    run()


if __name__ == "__main__":
    main()
