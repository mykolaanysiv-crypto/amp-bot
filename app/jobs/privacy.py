from __future__ import annotations

import asyncio
import logging

from ..observability import log_extra
from ..privacy_retention import cleanup_retained_data
from ..reliability import job_lock
from ..runtime_health import scheduler_heartbeat


async def _privacy_retention_scheduler(bot, db, settings) -> None:
    log = logging.getLogger("amp.privacy_retention")
    while True:
        await scheduler_heartbeat(db, "privacy_retention_scheduler")
        try:
            async with job_lock(db, "privacy_retention_cleanup", ttl_seconds=1800) as acquired:
                if acquired:
                    summary = await cleanup_retained_data(db, settings)
                    if summary.total:
                        log.info("Privacy retention cleanup removed %s records/files: %s", summary.total, summary.as_dict())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "Помилка retention cleanup",
                extra=log_extra("PRIVACY_RETENTION_CLEANUP_FAILED", scheduler="privacy_retention_scheduler", exception_type=type(exc).__name__),
            )
        await asyncio.sleep(24 * 3600)
