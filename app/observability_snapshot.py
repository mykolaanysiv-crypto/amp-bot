from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from .metrics import runtime_metrics
from .model_domains import MediaAsset, Notification, ScheduledJob
from .reliability import backup_verification_status
from .runtime_health import runtime_health_snapshot
from .time_utils import clock


async def build_observability_snapshot(session, db, settings) -> dict[str, object]:
    now = clock.storage_utc()
    runtime = await runtime_health_snapshot(
        session,
        worker_stale_seconds=settings.worker_stale_seconds,
        startup_grace_seconds=settings.health_startup_grace_seconds,
    )
    backup = await backup_verification_status(
        session,
        max_age_hours=settings.backup_max_age_hours,
        warning_age_hours=settings.backup_warning_age_hours,
        unknown_grace_hours=settings.backup_unknown_grace_hours,
    )
    queued_count = int(await session.scalar(select(func.count(Notification.id)).where(
        Notification.status.in_(["queued", "retry"])
    )) or 0)
    failed_count = int(await session.scalar(select(func.count(Notification.id)).where(
        Notification.status == "failed"
    )) or 0)
    oldest_scheduled = await session.scalar(select(func.min(Notification.scheduled_at)).where(
        Notification.status.in_(["queued", "retry"])
    ))
    queue_age_seconds = None
    if oldest_scheduled is not None:
        queue_age_seconds = max(0.0, (now - oldest_scheduled).total_seconds())

    recent_cutoff = now - timedelta(hours=24)
    scheduler_recent_failures = int(await session.scalar(select(func.count(ScheduledJob.job_name)).where(
        ScheduledJob.last_error_at.is_not(None), ScheduledJob.last_error_at >= recent_cutoff
    )) or 0)
    scheduler_failure_count = int(await session.scalar(select(func.coalesce(func.sum(ScheduledJob.failure_count), 0))) or 0)

    media_assets = int(await session.scalar(select(func.count(MediaAsset.id))) or 0)
    media_bytes = int(await session.scalar(select(func.coalesce(func.sum(MediaAsset.size_bytes), 0))) or 0)

    schedulers = runtime.get("schedulers") or []
    scheduler_ages = [float(row["age_seconds"]) for row in schedulers if row.get("age_seconds") is not None]
    max_scheduler_lag = round(max(scheduler_ages), 1) if scheduler_ages else None

    return {
        "runtime": runtime,
        "process_metrics": runtime_metrics.snapshot(window_seconds=900),
        "pool": db.pool_status(),
        "notifications": {
            "queued": queued_count,
            "failed": failed_count,
            "oldest_queue_age_seconds": round(queue_age_seconds, 1) if queue_age_seconds is not None else None,
        },
        "schedulers": {
            "max_lag_seconds": max_scheduler_lag,
            "recent_failed_jobs_24h": scheduler_recent_failures,
            "lifetime_failure_count": scheduler_failure_count,
        },
        "backup": backup,
        "media": {
            "assets": media_assets,
            "storage_bytes": media_bytes,
            "storage_megabytes": round(media_bytes / (1024 * 1024), 2),
        },
    }
