from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from aiogram import Bot
from fastapi import FastAPI

from .dependencies import bootstrap_defaults, db, log_extra, settings
from .broadcast_runtime import (
    _announce_version_update, _broadcast_retry_scheduler, _broadcast_tasks,
    _recover_pending_broadcasts, _retire_legacy_version_broadcasts,
)
from ..runtime_health import heartbeat_loop, runtime_health_alert

async def _runtime_health_monitor_loop(bot: Bot) -> None:
    # Give the worker enough time to boot after a deploy before declaring it
    # missing. Subsequent checks run from web, so a dead worker can still raise
    # a direct Telegram alarm to superadmins.
    await asyncio.sleep(settings.health_startup_grace_seconds)
    while True:
        try:
            await runtime_health_alert(
                bot, db, settings,
                repeat_seconds=settings.scheduler_alert_repeat_seconds,
                worker_stale_seconds=settings.worker_stale_seconds,
                startup_grace_seconds=settings.health_startup_grace_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger("amp.runtime_health").exception(
                "Помилка runtime health monitor",
                extra=log_extra("RUNTIME_HEALTH_MONITOR_FAILED", exception_type=type(exc).__name__),
            )
        await asyncio.sleep(60)

async def lifespan(app: FastAPI):
    smoke_mode = os.getenv("AMP_STARTUP_SMOKE", "").strip() == "1"
    app.state.startup_complete = False
    await db.init()
    await bootstrap_defaults(db, settings)

    background_tasks: list[asyncio.Task] = []
    health_bot: Bot | None = None
    if not smoke_mode:
        await _retire_legacy_version_broadcasts()
        await _recover_pending_broadcasts()
        await _announce_version_update()
        # Deadline/status housekeeping belongs to worker. The web process keeps
        # only broadcast recovery plus production health monitoring.
        background_tasks.append(asyncio.create_task(_broadcast_retry_scheduler(), name="broadcast_retry_scheduler"))
        background_tasks.append(asyncio.create_task(
            heartbeat_loop(db, "web", interval_seconds=settings.worker_heartbeat_seconds),
            name="web_heartbeat",
        ))
        if settings.bot_token and settings.superadmin_ids:
            health_bot = Bot(settings.bot_token)
            background_tasks.append(asyncio.create_task(
                _runtime_health_monitor_loop(health_bot), name="runtime_health_monitor"
            ))

    app.state.startup_complete = True
    try:
        yield
    finally:
        app.state.startup_complete = False
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        for task in list(_broadcast_tasks):
            task.cancel()
        if _broadcast_tasks:
            await asyncio.gather(*list(_broadcast_tasks), return_exceptions=True)
        if health_bot is not None:
            await health_bot.session.close()
        await db.close()
