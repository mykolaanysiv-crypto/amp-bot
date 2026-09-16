from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .bot_runtime import build_dispatcher, configure_bot_profile
from .config import get_settings
from .db import Database
from .jobs import scheduler_factories
from .runtime_health import heartbeat_loop, supervise_scheduler
from .services import bootstrap_defaults


async def main() -> None:
    settings = get_settings()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    db = Database(settings)
    await db.init()
    await bootstrap_defaults(db, settings)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await configure_bot_profile(bot)
    dp = build_dispatcher(bot, db, settings)

    worker_heartbeat_task = asyncio.create_task(
        heartbeat_loop(
            db,
            "worker",
            interval_seconds=settings.worker_heartbeat_seconds,
            initial_status="running",
        ),
        name="worker_heartbeat",
    )
    factories = scheduler_factories(bot, db, settings)
    scheduler_tasks = [
        asyncio.create_task(
            supervise_scheduler(name, factory, db=db, bot=bot, settings=settings),
            name=f"supervisor:{name}",
        )
        for name, factory in factories.items()
    ]
    try:
        await dp.start_polling(bot, db=db, settings=settings)
    finally:
        worker_heartbeat_task.cancel()
        for task in scheduler_tasks:
            task.cancel()
        await asyncio.gather(worker_heartbeat_task, *scheduler_tasks, return_exceptions=True)
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
