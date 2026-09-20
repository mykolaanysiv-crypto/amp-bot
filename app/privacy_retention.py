from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, or_, select

from .db import Database
from .domain_services import log_audit
from .model_domains import MediaAsset, Notification, NotificationDelivery, RegistrationJourney, WebAdminSession
from .runtime_config import get_runtime_int
from .time_utils import clock

TEMP_MEDIA_CATEGORIES = {"temp", "temporary", "registration_tmp", "tmp"}


@dataclass(slots=True)
class RetentionSummary:
    abandoned_registration_drafts: int = 0
    completed_registration_journeys: int = 0
    old_web_sessions: int = 0
    old_notifications: int = 0
    old_notification_deliveries: int = 0
    temp_media_assets: int = 0
    temp_local_files: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def total(self) -> int:
        return sum(self.as_dict().values())


def _cleanup_local_temp_files(data_dir: str, cutoff_ts: float) -> int:
    removed = 0
    roots = [Path(data_dir) / "tmp", Path(data_dir) / "uploads" / "tmp", Path(data_dir) / "private" / "tmp"]
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff_ts:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
    return removed


async def cleanup_retained_data(db: Database, settings, *, actor_label: str = "Система АМП") -> RetentionSummary:
    """Apply the v1.17.2 retention policy to transient/service data only.

    User profiles, XP history, attendance history, audit logs and consent history
    are intentionally excluded. This cleanup is conservative and auditable.
    """
    now = clock.storage_utc()
    summary = RetentionSummary()
    async with db.session_factory() as session:
        draft_days = await get_runtime_int(session, "privacy.registration_draft_days")
        journey_days = await get_runtime_int(session, "privacy.completed_journey_days")
        session_days = await get_runtime_int(session, "privacy.session_history_days")
        service_days = await get_runtime_int(session, "privacy.service_records_days")
        temp_days = await get_runtime_int(session, "privacy.temp_files_days")

        draft_cutoff = now - timedelta(days=draft_days)
        journey_cutoff = now - timedelta(days=journey_days)
        session_cutoff = now - timedelta(days=session_days)
        service_cutoff = now - timedelta(days=service_days)
        temp_cutoff = now - timedelta(days=temp_days)

        result = await session.execute(delete(RegistrationJourney).where(
            RegistrationJourney.submitted_at.is_(None),
            RegistrationJourney.updated_at < draft_cutoff,
        ))
        summary.abandoned_registration_drafts = int(result.rowcount or 0)

        result = await session.execute(delete(RegistrationJourney).where(
            RegistrationJourney.submitted_at.is_not(None),
            RegistrationJourney.updated_at < journey_cutoff,
        ))
        summary.completed_registration_journeys = int(result.rowcount or 0)

        result = await session.execute(delete(WebAdminSession).where(
            WebAdminSession.last_seen_at < session_cutoff,
            or_(
                WebAdminSession.revoked_at.is_not(None),
                WebAdminSession.expires_at.is_not(None) & (WebAdminSession.expires_at < now),
            ),
        ))
        summary.old_web_sessions = int(result.rowcount or 0)

        result = await session.execute(delete(Notification).where(
            Notification.status.in_(["sent", "failed"]),
            Notification.updated_at < service_cutoff,
        ))
        summary.old_notifications = int(result.rowcount or 0)

        result = await session.execute(delete(NotificationDelivery).where(
            NotificationDelivery.status.in_(["sent", "failed"]),
            NotificationDelivery.updated_at < service_cutoff,
        ))
        summary.old_notification_deliveries = int(result.rowcount or 0)

        temp_ids = list((await session.scalars(select(MediaAsset.id).where(
            MediaAsset.category.in_(TEMP_MEDIA_CATEGORIES),
            MediaAsset.created_at < temp_cutoff,
        ))).all())
        if temp_ids:
            result = await session.execute(delete(MediaAsset).where(MediaAsset.id.in_(temp_ids)))
            summary.temp_media_assets = int(result.rowcount or 0)

        if summary.total:
            await log_audit(
                session,
                "privacy_retention_cleanup",
                actor_label=actor_label,
                entity_type="system",
                details=str(summary.as_dict()),
            )
        await session.commit()

    summary.temp_local_files = _cleanup_local_temp_files(
        settings.data_dir,
        (clock.now_utc() - timedelta(days=temp_days)).timestamp(),
    )
    return summary
