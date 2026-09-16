from __future__ import annotations

"""Production lifecycle smoke for AMP production releases (v1.13.0 factory-aware).

This script deliberately executes the same critical sequence used during a
release:

    db.init() -> bootstrap_defaults() -> Alembic upgrade head -> FastAPI lifespan

It is safe for production data: the bootstrap is idempotent, Alembic only moves
forward, and AMP_STARTUP_SMOKE disables participant-facing startup broadcasts
and long-running background tasks while the real web lifespan is entered.
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


async def _legacy_bootstrap_phase() -> None:
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    try:
        await db.init()
        await bootstrap_defaults(db, settings)
    finally:
        await db.close()


async def _web_startup_phase() -> None:
    # Import only after Alembic so web objects are created against the schema
    # the release will actually expose. v1.13.0 exercises the canonical factory
    # directly and then imports the compatibility facade as an import-regression
    # check for the planned 1–2 release transition window.
    factory_module = importlib.import_module("app.web.factory")
    app = factory_module.create_app()
    compatibility_module = importlib.import_module("app.web.app")
    if not hasattr(compatibility_module, "app"):
        raise RuntimeError("app.web.app compatibility facade missing module-level app")
    async with app.router.lifespan_context(app):
        if not bool(getattr(app.state, "startup_complete", False)):
            raise RuntimeError("FastAPI lifespan entered without startup_complete")
        # Import the worker module too. This catches refactor/import regressions
        # before production even though Telegram polling is intentionally not
        # started in a release dyno.
        importlib.import_module("app.main")


def run() -> None:
    # Exact critical order requested for the production gate.
    asyncio.run(_legacy_bootstrap_phase())

    from scripts.alembic_bootstrap import upgrade_head
    upgrade_head()

    with _smoke_environment():
        asyncio.run(_web_startup_phase())

    log.info("Production lifecycle smoke PASS: db.init -> bootstrap -> Alembic -> web lifespan")


def main() -> None:
    if not logging.getLogger().handlers:
        configure_observability(service="startup-smoke")
    run()


if __name__ == "__main__":
    main()
