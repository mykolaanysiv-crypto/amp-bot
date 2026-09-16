from __future__ import annotations
import asyncio
import logging
from aiogram import Bot
from ..db import Database
from ..observability import log_extra
from ..reliability import backup_health_alert, job_lock, notification_failure_alert, process_due_telegram_deliveries
from ..runtime_health import scheduler_heartbeat

async def _notification_retry_scheduler(bot: Bot, db: Database) -> None:
    """Drain the durable Telegram outbox every minute."""
    log = logging.getLogger("amp.notification_retry")
    while True:
        await scheduler_heartbeat(db, "notification_retry_scheduler")
        try:
            summary = await process_due_telegram_deliveries(bot, db, limit=80)
            if summary["processed"]:
                log.info(
                    "Telegram outbox: processed=%s sent=%s retry=%s failed=%s",
                    summary["processed"], summary["sent"], summary["retry"], summary["failed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка retry-планувальника Telegram", extra=log_extra("SCHED_NOTIFICATION_RETRY_FAILED", scheduler="notification_retry_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(15)

async def _notification_health_scheduler(bot: Bot, db: Database, settings) -> None:
    log = logging.getLogger("amp.notification_health")
    while True:
        await scheduler_heartbeat(db, "notification_health_scheduler")
        try:
            async with job_lock(db, "notification_failure_alert", ttl_seconds=240) as acquired:
                if acquired:
                    await notification_failure_alert(bot, db, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка моніторингу failed Notification Center", extra=log_extra("SCHED_NOTIFICATION_HEALTH_FAILED", scheduler="notification_health_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(300)

async def _backup_health_scheduler(bot: Bot, db: Database, settings) -> None:
    """Verify the externally recorded backup marker and alert at most daily."""
    log = logging.getLogger("amp.backup_health")
    while True:
        await scheduler_heartbeat(db, "backup_health_scheduler")
        try:
            async with job_lock(db, "backup_health_alert", ttl_seconds=240) as acquired:
                if acquired:
                    await backup_health_alert(
                        bot, db, settings,
                        unknown_grace_hours=settings.backup_unknown_grace_hours,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка перевірки резервних копій", extra=log_extra("SCHED_BACKUP_HEALTH_FAILED", scheduler="backup_health_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(6 * 3600)
