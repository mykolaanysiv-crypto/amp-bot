from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from .model_domains import AuditLog, GamificationRuleVersion, OperationalIssue, Event, EventFeedback, EventRegistration, Notification, RewardClaim, User, XPTransaction, SystemSetting
from .reliability import backup_verification_status
from .runtime_config import get_runtime_int
from .time_utils import clock

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _v(value: Any) -> str:
    if value is None: return ""
    return str(value)

async def record_rule_change(session: AsyncSession, *, rule_key: str, field_name: str, old_value: Any, new_value: Any,
                             author_label: str, reason: str, entity_type: str="system", entity_id: int|None=None,
                             effective_at: datetime|None=None) -> GamificationRuleVersion | None:
    if _v(old_value) == _v(new_value): return None
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Для зміни правила гейміфікації обов’язково вкажіть причину.")
    row = GamificationRuleVersion(rule_key=rule_key, entity_type=entity_type, entity_id=entity_id,
        field_name=field_name, old_value=_v(old_value), new_value=_v(new_value), author_label=author_label or "web",
        reason=reason, effective_at=effective_at or clock.storage_utc(), created_at=clock.storage_utc())
    session.add(row)
    return row


async def record_field_changes(session: AsyncSession, *, rule_prefix: str, entity_type: str, entity_id: int | None,
                               old_values: dict[str, Any], new_values: dict[str, Any], author_label: str,
                               reason: str = "Зміна через вебпанель", fields: set[str] | None = None) -> int:
    """Append-only governance history for fields that affect gamification rules.

    This never mutates XP/wallet history; it only records the configuration change.
    """
    changed = 0
    for field_name, new_value in new_values.items():
        if fields is not None and field_name not in fields:
            continue
        old_value = old_values.get(field_name)
        if _v(old_value) == _v(new_value):
            continue
        await record_rule_change(
            session, rule_key=f"{rule_prefix}.{field_name}", field_name=field_name,
            old_value=old_value, new_value=new_value, author_label=author_label,
            reason=(reason or "Зміна через вебпанель").strip(), entity_type=entity_type, entity_id=entity_id,
        )
        changed += 1
    return changed

# Existing schema is sufficient: operator decisions and system transitions are
# recorded in append-only audit_logs; no changes to participant XP are made.
SCAN_SETTING_KEY = "operations.last_scan_at"
REMINDER_GRACE_MINUTES = 10  # Scheduler polls every 5 minutes; allow two cycles.


def reminder_is_overdue(event_start: datetime, local_now: datetime, lead_minutes: int) -> bool:
    """Match the event scheduler's local-wall time semantics without early alarms."""
    return (
        local_now < event_start
        and local_now >= event_start - timedelta(minutes=max(0, lead_minutes))
        + timedelta(minutes=REMINDER_GRACE_MINUTES)
    )


def _audit_transition(session: AsyncSession, row: OperationalIssue, action: str, details: str) -> None:
    session.add(AuditLog(actor_label="system:operational_scanner", action=action,
        entity_type="operational_issue", entity_id=row.id, details=details[:2000],
        created_at=clock.storage_utc()))


async def _upsert_issue(session: AsyncSession, *, fingerprint: str, issue_type: str, severity: str, title: str,
                        details: str, action_url: str, entity_type: str|None=None, entity_id: int|None=None,
                        assignee_label: str="") -> OperationalIssue:
    now = clock.storage_utc()
    row = await session.scalar(select(OperationalIssue).where(OperationalIssue.fingerprint == fingerprint))
    if row:
        if row.status == "resolved":
            # An operator's decision is auditable, but it cannot suppress an
            # independently detected, still-active problem on later scans.
            _audit_transition(session, row, "operational_issue_auto_reopened",
                f"{fingerprint}; попереднє вирішення: {row.resolution_note or '—'}")
            row.status = "open"
            row.resolved_at = None
            row.resolved_by = None
            row.resolution_note = ""
        row.last_seen_at = now
        row.occurrence_count = int(row.occurrence_count or 0) + 1
        row.severity = severity
        row.title = title
        row.details = details
        row.action_url = action_url
        row.entity_type = entity_type
        row.entity_id = entity_id
        if assignee_label:
            row.assignee_label = assignee_label
        return row
    row = OperationalIssue(fingerprint=fingerprint, issue_type=issue_type, severity=severity,
        title=title, details=details, action_url=action_url, entity_type=entity_type,
        entity_id=entity_id, assignee_label=assignee_label, status="open",
        first_seen_at=now, last_seen_at=now, occurrence_count=1)
    session.add(row)
    return row


async def scan_operational_issues(session: AsyncSession, *, backup_max_age_hours: int=168,
                                  now: datetime | None = None) -> int:
    """One complete transactional scan. Call only under the distributed job lock.

    An exception must roll back the session: otherwise unseen issues could be
    incorrectly marked resolved by an incomplete pass.
    """
    now = now or clock.storage_utc()
    local_now = clock.local_wall(clock.from_storage_utc(now))
    observed: set[str] = set()

    async def report(*, fingerprint: str, **kwargs) -> None:
        await _upsert_issue(session, fingerprint=fingerprint, **kwargs)
        observed.add(fingerprint)

    # No LIMIT: closing unseen issues is safe only after checking every account.
    rows = (await session.scalars(select(User).where(
        User.registration_review_status == "pending",
        User.created_at <= now - timedelta(hours=24)
    ))).all()
    for user in rows:
        await report(fingerprint=f"registration_stale:{user.id}", issue_type="registration_stale",
            severity="high", title="Реєстрація очікує понад 24 год",
            details=f"Учасник АМП-{user.id:04d}: {user.full_name}",
            action_url="/admin/registrations", entity_type="user", entity_id=user.id)

    failed = int(await session.scalar(select(func.count(Notification.id)).where(
        Notification.status == "failed")) or 0)
    if failed:
        await report(fingerprint="notifications_failed", issue_type="failed_notifications",
            severity="high", title="Є невідправлені повідомлення",
            details=f"Failed notifications: {failed}", action_url="/admin/notifications")

    # A reminder is overdue only AFTER its configured scheduling window. A
    # successfully queued reminder is tracked by reminder_1h_sent_at; actual
    # delivery failures are independently reported by notifications_failed.
    reminder_minutes = await get_runtime_int(session, "events.reminder_minutes")
    next_day = local_now + timedelta(hours=24)
    pending_reminders = (await session.execute(
        select(Event.id, Event.title, Event.starts_at, func.count(EventRegistration.id))
        .join(EventRegistration, EventRegistration.event_id == Event.id)
        .join(User, User.id == EventRegistration.user_id)
        .where(Event.status.in_(["open", "postponed"]),
            Event.starts_at > local_now, Event.starts_at <= next_day,
            EventRegistration.status.in_(["registered", "reserved", "checked_in"]),
            EventRegistration.reminder_1h_sent_at.is_(None), User.status == "active")
        .group_by(Event.id, Event.title, Event.starts_at)
    )).all()
    for event_id, title, starts_at, pending in pending_reminders:
        if reminder_is_overdue(starts_at, local_now, reminder_minutes):
            await report(fingerprint=f"event_no_reminder:{event_id}", issue_type="event_no_reminder",
                severity="high", title="Нагадування про подію прострочене",
                details=f"{title}: {pending} учасників без нагадування (ліміт {reminder_minutes} хв до початку)",
                action_url=f"/admin/events/{event_id}", entity_type="event", entity_id=event_id)

    feedback_rows = (await session.execute(
        select(Event.id, Event.title, func.count(EventFeedback.id),
            func.sum(case((EventFeedback.status == "completed", 1), else_=0)))
        .join(EventFeedback, EventFeedback.event_id == Event.id)
        .where(EventFeedback.prompted_at.is_not(None))
        .group_by(Event.id, Event.title)
    )).all()
    for event_id, title, total, completed in feedback_rows:
        total, completed = int(total or 0), int(completed or 0)
        rate = (completed * 100 / total) if total else 100
        if total >= 3 and rate < 30:
            await report(fingerprint=f"feedback_low:{event_id}", issue_type="feedback_low",
                severity="medium", title="Feedback нижче 30%",
                details=f"{title}: {completed}/{total} ({rate:.0f}%)",
                action_url=f"/admin/events/{event_id}", entity_type="event", entity_id=event_id)

    expired = int(await session.scalar(select(func.count(EventRegistration.id)).where(
        EventRegistration.status == "reserved",
        EventRegistration.reservation_expires_at.is_not(None),
        EventRegistration.reservation_expires_at < now)) or 0)
    if expired:
        await report(fingerprint="expired_reservations", issue_type="expired_reservations",
            severity="medium", title="Прострочений резерв не опрацьований",
            details=f"Прострочених reservations: {expired}", action_url="/admin/events")

    # Single grouped query replaces one ledger SUM per participant (N+1).
    wallet_rows = (await session.execute(
        select(User.id, User.wallet_xp, func.coalesce(func.sum(XPTransaction.amount), 0))
        .outerjoin(XPTransaction, XPTransaction.user_id == User.id)
        .where(User.status != "deleted_permanent")
        .group_by(User.id, User.wallet_xp)
    )).all()
    for user_id, wallet_raw, earned_raw in wallet_rows:
        wallet, earned = int(wallet_raw or 0), int(earned_raw or 0)
        if wallet < 0 or wallet > max(0, earned):
            await report(fingerprint=f"xp_wallet:{user_id}", issue_type="xp_anomaly",
                severity="critical", title="Аномалія XP / wallet",
                details=f"АМП-{user_id:04d}: wallet={wallet}, ledger={earned}",
                action_url=f"/admin/users/{user_id}", entity_type="user", entity_id=user_id)

    bad_claims = int(await session.scalar(select(func.count(RewardClaim.id)).where(
        RewardClaim.xp_spent < 0)) or 0)
    if bad_claims:
        await report(fingerprint="reward_claim_negative", issue_type="reward_anomaly",
            severity="critical", title="Некоректні reward claims",
            details=f"Заявок із від’ємним списанням XP: {bad_claims}", action_url="/admin/rewards")

    backup = await backup_verification_status(session, max_age_hours=backup_max_age_hours,
                                               unknown_grace_hours=0)
    if not backup.get("ok"):
        await report(fingerprint="backup_stale", issue_type="backup_stale",
            severity="critical", title="Backup потребує уваги",
            details=f"Стан: {backup.get('status')}; вік: {backup.get('age_hours') if backup.get('age_hours') is not None else '—'} год",
            action_url="/admin/system-health")

    # Only after every source has been checked can vanished issues be closed.
    open_rows = (await session.scalars(select(OperationalIssue).where(
        OperationalIssue.status == "open"))).all()
    for row in open_rows:
        if row.fingerprint not in observed:
            row.status = "resolved"
            row.resolved_at = now
            row.resolved_by = "system:operational_scanner"
            row.resolution_note = "Причина більше не виявляється під час повного сканування."
            _audit_transition(session, row, "operational_issue_auto_resolved", row.fingerprint)

    marker = await session.get(SystemSetting, SCAN_SETTING_KEY)
    if marker:
        marker.value, marker.updated_at = now.isoformat(), now
    else:
        session.add(SystemSetting(key=SCAN_SETTING_KEY, value=now.isoformat(), updated_at=now))
    return len(observed)
