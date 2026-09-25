from __future__ import annotations

import asyncio
import logging

from ..db import Database
from ..governance import scan_operational_issues
from ..observability import log_extra
from ..reliability import job_lock
from ..runtime_health import scheduler_heartbeat


async def _operational_scan_scheduler(bot, db: Database, settings) -> None:
    """Expensive operations scan only in the worker, never on page refresh."""
    log = logging.getLogger("amp.operational_scan")
    while True:
        await scheduler_heartbeat(db, "operational_scan_scheduler")
        try:
            async with job_lock(db, "operational_scan", ttl_seconds=600) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        seen = await scan_operational_issues(session)
                        await session.commit()
                        log.info("Operational scan completed; active signals=%s", seen)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка операційного сканування",
                extra=log_extra("SCHED_OPERATIONAL_SCAN_FAILED",
                    scheduler="operational_scan_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(15 * 60)
