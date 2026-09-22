from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from .model_domains import GamificationRuleVersion, OperationalIssue, Event, EventFeedback, EventRegistration, Notification, RewardClaim, User, XPTransaction, SystemSetting
from .reliability import backup_verification_status
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

async def _upsert_issue(session: AsyncSession, *, fingerprint: str, issue_type: str, severity: str, title: str,
                        details: str, action_url: str, entity_type: str|None=None, entity_id: int|None=None,
                        assignee_label: str="") -> OperationalIssue:
    now=clock.storage_utc()
    row=await session.scalar(select(OperationalIssue).where(OperationalIssue.fingerprint==fingerprint))
    if row:
        row.last_seen_at=now; row.occurrence_count=int(row.occurrence_count or 0)+1
        row.severity=severity; row.title=title; row.details=details; row.action_url=action_url
        row.entity_type=entity_type; row.entity_id=entity_id
        if assignee_label: row.assignee_label=assignee_label
        return row
    row=OperationalIssue(fingerprint=fingerprint, issue_type=issue_type, severity=severity, title=title, details=details,
        action_url=action_url, entity_type=entity_type, entity_id=entity_id, assignee_label=assignee_label,
        status="open", first_seen_at=now, last_seen_at=now, occurrence_count=1)
    session.add(row); return row

async def scan_operational_issues(session: AsyncSession, *, backup_max_age_hours: int=168) -> int:
    now=clock.storage_utc(); local_now=clock.local_wall()
    seen=0
    # Registration pending >24h.
    rows=(await session.scalars(select(User).where(User.registration_review_status=="pending", User.created_at <= now-timedelta(hours=24)).limit(100))).all()
    for u in rows:
        await _upsert_issue(session,fingerprint=f"registration_stale:{u.id}",issue_type="registration_stale",severity="high",
            title="Реєстрація очікує понад 24 год",details=f"Учасник АМП-{u.id:04d}: {u.full_name}",action_url="/admin/registrations",entity_type="user",entity_id=u.id); seen+=1
    # Failed notifications grouped as a concrete queue task.
    failed=int(await session.scalar(select(func.count(Notification.id)).where(Notification.status=="failed")) or 0)
    if failed:
        await _upsert_issue(session,fingerprint="notifications_failed",issue_type="failed_notifications",severity="high",
            title="Є невідправлені повідомлення",details=f"Failed notifications: {failed}",action_url="/admin/notifications"); seen+=1
    # Tomorrow event with registered people but no queued reminder and no sent marker.
    tomorrow=(local_now+timedelta(days=1)).date(); start=datetime.combine(tomorrow, datetime.min.time()); end=start+timedelta(days=1)
    events=(await session.scalars(select(Event).where(Event.status.in_(["open","postponed"]),Event.starts_at>=start,Event.starts_at<end))).all()
    for event in events:
        regs=int(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.event_id==event.id,EventRegistration.status.in_(["registered","reserved"]))) or 0)
        sent=int(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.event_id==event.id,EventRegistration.reminder_1h_sent_at.is_not(None))) or 0)
        if regs and not sent:
            await _upsert_issue(session,fingerprint=f"event_no_reminder:{event.id}",issue_type="event_no_reminder",severity="medium",
                title="Подія завтра без нагадування",details=f"{event.title}: {regs} зареєстрованих",action_url=f"/admin/events/{event.id}",entity_type="event",entity_id=event.id); seen+=1
    # Feedback below 30% for events that actually prompted feedback.
    feedback_rows=(await session.execute(select(Event.id,Event.title,func.count(EventFeedback.id),func.sum(case((EventFeedback.status=="completed",1),else_=0))).join(EventFeedback,EventFeedback.event_id==Event.id).where(EventFeedback.prompted_at.is_not(None)).group_by(Event.id,Event.title))).all()
    for eid,title,total,completed in feedback_rows:
        total=int(total or 0); completed=int(completed or 0); rate=(completed*100/total) if total else 100
        if total>=3 and rate<30:
            await _upsert_issue(session,fingerprint=f"feedback_low:{eid}",issue_type="feedback_low",severity="medium",title="Feedback нижче 30%",
                details=f"{title}: {completed}/{total} ({rate:.0f}%)",action_url=f"/admin/events/{eid}",entity_type="event",entity_id=eid); seen+=1
    # Expired reservations that still carry reserved state.
    expired=int(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.status=="reserved",EventRegistration.reservation_expires_at.is_not(None),EventRegistration.reservation_expires_at<now)) or 0)
    if expired:
        await _upsert_issue(session,fingerprint="expired_reservations",issue_type="expired_reservations",severity="medium",title="Прострочений резерв не опрацьований",
            details=f"Прострочених reservations: {expired}",action_url="/admin/events"); seen+=1
    # XP/wallet anomalies: wallet negative or wallet above lifetime positive XP.
    users=(await session.scalars(select(User).where(User.status.not_in(["deleted_permanent"])))).all()
    for u in users:
        earned=int(await session.scalar(select(func.coalesce(func.sum(XPTransaction.amount),0)).where(XPTransaction.user_id==u.id)) or 0)
        if int(u.wallet_xp or 0)<0 or int(u.wallet_xp or 0)>max(0,earned):
            await _upsert_issue(session,fingerprint=f"xp_wallet:{u.id}",issue_type="xp_anomaly",severity="critical",title="Аномалія XP / wallet",
                details=f"АМП-{u.id:04d}: wallet={u.wallet_xp}, ledger={earned}",action_url=f"/admin/users/{u.id}",entity_type="user",entity_id=u.id); seen+=1
    # Reward claims impossible values.
    bad_claims=int(await session.scalar(select(func.count(RewardClaim.id)).where(RewardClaim.xp_spent<0)) or 0)
    if bad_claims:
        await _upsert_issue(session,fingerprint="reward_claim_negative",issue_type="reward_anomaly",severity="critical",title="Некоректні reward claims",
            details=f"Заявок із від’ємним списанням XP: {bad_claims}",action_url="/admin/rewards"); seen+=1
    # Verified backup stale/missing.
    backup=await backup_verification_status(session,max_age_hours=backup_max_age_hours,unknown_grace_hours=0)
    if not backup.get("ok"):
        await _upsert_issue(session,fingerprint="backup_stale",issue_type="backup_stale",severity="critical",title="Backup потребує уваги",
            details=f"Стан: {backup.get('status')}; вік: {backup.get('age_hours') or '—'} год",action_url="/admin/system-health"); seen+=1
    return seen
