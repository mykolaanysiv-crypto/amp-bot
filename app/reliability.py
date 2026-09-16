from __future__ import annotations

from .observability import log_extra
from .time_utils import clock

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from aiogram.exceptions import TelegramForbiddenError

from .models import (
    BroadcastCampaign,
    BroadcastRecipient,
    Notification,
    ScheduledJob,
    SystemSetting,
    User,
    UserRole,
    UserStatus,
)

log = logging.getLogger(__name__)

RETRY_DELAYS_SECONDS = (60, 300, 900)
DEFAULT_MAX_ATTEMPTS = 4


def worker_id() -> str:
    dyno = os.getenv("DYNO", "").strip()
    host = socket.gethostname()
    return (dyno or host or "worker") + f":{os.getpid()}"


async def acquire_job_lock(db, job_name: str, *, ttl_seconds: int = 300, owner: str | None = None) -> str | None:
    owner = owner or worker_id()
    now = clock.storage_utc()
    locked_until = now + timedelta(seconds=max(30, int(ttl_seconds)))
    async with db.session_factory() as session:
        stmt = (
            update(ScheduledJob)
            .where(
                ScheduledJob.job_name == job_name,
                or_(ScheduledJob.locked_until.is_(None), ScheduledJob.locked_until <= now),
            )
            .values(
                locked_at=now,
                locked_until=locked_until,
                locked_by=owner,
                last_started_at=now,
                run_count=ScheduledJob.run_count + 1,
                updated_at=now,
            )
        )
        result = await session.execute(stmt)
        if result.rowcount:
            await session.commit()
            return owner
        try:
            async with session.begin_nested():
                session.add(ScheduledJob(job_name=job_name, locked_at=now, locked_until=locked_until, locked_by=owner, last_started_at=now, run_count=1, updated_at=now))
                await session.flush()
            await session.commit()
            return owner
        except IntegrityError:
            await session.rollback()
            return None


async def finish_job_lock(db, job_name: str, owner: str, *, success: bool, error: str = "") -> None:
    now = clock.storage_utc()
    values = {"locked_at": None, "locked_until": None, "locked_by": None, "updated_at": now}
    if success:
        values.update(last_success_at=now, last_error="")
    else:
        values.update(last_error_at=now, last_error=(error or "Unknown scheduler error")[:2000], failure_count=ScheduledJob.failure_count + 1)
    async with db.session_factory() as session:
        await session.execute(update(ScheduledJob).where(ScheduledJob.job_name == job_name, ScheduledJob.locked_by == owner).values(**values))
        await session.commit()


@asynccontextmanager
async def job_lock(db, job_name: str, *, ttl_seconds: int = 300) -> AsyncIterator[bool]:
    owner = await acquire_job_lock(db, job_name, ttl_seconds=ttl_seconds)
    if not owner:
        yield False
        return
    try:
        yield True
    except asyncio.CancelledError:
        await finish_job_lock(db, job_name, owner, success=True)
        raise
    except Exception as exc:
        await finish_job_lock(db, job_name, owner, success=False, error=str(exc))
        raise
    else:
        await finish_job_lock(db, job_name, owner, success=True)


def notification_type_for_source(source: str | None) -> str:
    value = (source or "system").lower()
    if "broadcast" in value or value in {"web", "system_update", "system_version_update"}:
        return "broadcast" if "broadcast" in value else "system"
    if any(x in value for x in ("event", "attendance", "waitlist", "feedback")):
        return "event"
    if any(x in value for x in ("case", "request")):
        return "case"
    if "streak" in value:
        return "streak"
    if "survey" in value:
        return "survey"
    return "system"


def _default_title(notification_type: str, source: str | None) -> str:
    labels = {
        "system": "Системне сповіщення",
        "event": "Події",
        "broadcast": "Розсилка",
        "case": "Звернення",
        "streak": "Серії участі",
        "survey": "Опитування",
    }
    return labels.get(notification_type, (source or "Сповіщення").replace("_", " ").title())


async def queue_notification(
    session,
    tg_id: int | None,
    body: str,
    *,
    source: str = "system",
    notification_type: str | None = None,
    title: str | None = None,
    recipient_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    scheduled_at: datetime | None = None,
    dedupe_key: str | None = None,
    parse_mode: str | None = "HTML",
    button_text: str | None = None,
    callback_data: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Notification | None:
    """Create the single canonical v1.9 notification/outbox row."""
    if not tg_id or not body:
        return None
    ntype = notification_type or notification_type_for_source(source)
    if recipient_user_id is None:
        recipient_user_id = await session.scalar(select(User.id).where(User.tg_id == int(tg_id)))
    if dedupe_key:
        existing = await session.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
        if existing:
            return existing
    row = Notification(
        dedupe_key=dedupe_key,
        recipient_user_id=recipient_user_id,
        recipient_tg_id=int(tg_id),
        type=ntype[:48],
        title=(title or _default_title(ntype, source))[:180],
        body=body,
        entity_type=(entity_type or None),
        entity_id=entity_id,
        scheduled_at=scheduled_at or clock.storage_utc(),
        status="queued",
        retry_count=0,
        max_attempts=max(1, int(max_attempts or DEFAULT_MAX_ATTEMPTS)),
        parse_mode=parse_mode,
        button_text=(button_text or None),
        callback_data=(callback_data or None),
    )
    if not dedupe_key:
        session.add(row)
        await session.flush()
        return row
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
        return row
    except IntegrityError:
        return await session.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))


async def queue_telegram_delivery(
    session,
    tg_id: int | None,
    text: str,
    *,
    source: str,
    dedupe_key: str | None = None,
    parse_mode: str | None = "HTML",
    button_text: str | None = None,
    callback_data: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    notification_type: str | None = None,
    title: str | None = None,
    recipient_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    scheduled_at: datetime | None = None,
) -> Notification | None:
    """Backward-compatible name. New deliveries are stored only in notifications."""
    return await queue_notification(
        session,
        tg_id,
        text,
        source=source,
        notification_type=notification_type,
        title=title,
        recipient_user_id=recipient_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        scheduled_at=scheduled_at,
        dedupe_key=dedupe_key,
        parse_mode=parse_mode,
        button_text=button_text,
        callback_data=callback_data,
        max_attempts=max_attempts,
    )


def _retry_delay(attempt_count: int) -> int:
    idx = min(max(1, attempt_count), len(RETRY_DELAYS_SECONDS)) - 1
    return RETRY_DELAYS_SECONDS[idx]


def _feedback_markup(notification: Notification):
    """Build interactive feedback keyboards from notification metadata."""
    if not (notification.entity_type or "").startswith("event_feedback") or not notification.entity_id:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    fid = int(notification.entity_id)
    if notification.entity_type == "event_feedback_rating":
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=str(value), callback_data=f"feedback:rating:{fid}:{value}") for value in range(1, 6)
        ]])
    mapping = {
        "event_feedback_useful": "useful",
        "event_feedback_knowledge": "knowledge",
        "event_feedback_safe": "safe",
        "event_feedback_return": "return",
    }
    field = mapping.get(notification.entity_type)
    if field:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Так", callback_data=f"feedback:yn:{fid}:{field}:1"), InlineKeyboardButton(text="❌ Ні", callback_data=f"feedback:yn:{fid}:{field}:0")]])
    return None


def _generic_markup(notification: Notification):
    markup = _feedback_markup(notification)
    if markup is not None:
        return markup
    if notification.button_text and notification.callback_data:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=notification.button_text, callback_data=notification.callback_data)]])
    return None


async def _sync_legacy_broadcast(session, notification: Notification) -> None:
    if notification.entity_type != "broadcast_recipient" or not notification.entity_id:
        return
    recipient = await session.get(BroadcastRecipient, int(notification.entity_id))
    if not recipient:
        return
    recipient.attempt_count = int(notification.retry_count or 0)
    recipient.last_attempt_at = notification.last_attempt_at
    recipient.sent_at = notification.sent_at
    recipient.error_text = notification.error or ""
    recipient.next_retry_at = notification.scheduled_at if notification.status == "retry" else None
    recipient.status = {"queued": "pending", "retry": "retry", "sent": "sent", "failed": "failed"}.get(notification.status, notification.status)
    campaign = await session.get(BroadcastCampaign, recipient.campaign_id)
    if not campaign:
        return
    sent = int(await session.scalar(select(func.count(BroadcastRecipient.id)).where(BroadcastRecipient.campaign_id == campaign.id, BroadcastRecipient.status == "sent")) or 0)
    failed = int(await session.scalar(select(func.count(BroadcastRecipient.id)).where(BroadcastRecipient.campaign_id == campaign.id, BroadcastRecipient.status == "failed")) or 0)
    pending = int(await session.scalar(select(func.count(BroadcastRecipient.id)).where(BroadcastRecipient.campaign_id == campaign.id, BroadcastRecipient.status.in_(["pending", "retry"]))) or 0)
    campaign.sent_count = sent
    campaign.failed_count = failed
    if pending:
        campaign.status = "sending"
        campaign.completed_at = None
    else:
        campaign.status = "completed_with_errors" if failed else "completed"
        campaign.completed_at = clock.storage_utc()


async def send_notification_now(bot, session, notification: Notification) -> bool:
    """Try to deliver one queued notification immediately and persist its state.

    ``retry_count`` is the number of failed attempts already made, not the
    number of total sends. A first-attempt success therefore stays at 0.
    """
    if notification.status == "sent":
        return True
    notification.last_attempt_at = clock.storage_utc()
    notification.updated_at = notification.last_attempt_at
    try:
        await bot.send_message(notification.recipient_tg_id, notification.body, parse_mode=notification.parse_mode, reply_markup=_generic_markup(notification))
        notification.status = "sent"
        notification.sent_at = clock.storage_utc()
        notification.error = ""
        await _sync_legacy_broadcast(session, notification)
        return True
    except Exception as exc:
        next_retry_count = int(notification.retry_count or 0) + 1
        notification.retry_count = next_retry_count
        notification.error = str(exc)[:500]
        if next_retry_count >= int(notification.max_attempts or DEFAULT_MAX_ATTEMPTS):
            notification.status = "failed"
        else:
            notification.status = "retry"
            notification.scheduled_at = clock.storage_utc() + timedelta(seconds=_retry_delay(next_retry_count))
        await _sync_legacy_broadcast(session, notification)
        return False


async def notify_now(
    bot, session, tg_id: int | None, body: str, *, source: str = "system",
    title: str | None = None, recipient_user_id: int | None = None,
    entity_type: str | None = None, entity_id: int | None = None,
    dedupe_key: str | None = None, notification_type: str | None = None,
    button_text: str | None = None, callback_data: str | None = None,
    parse_mode: str | None = "HTML",
) -> Notification | None:
    """Queue and immediately try one notification through the canonical center."""
    row = await queue_notification(
        session, tg_id, body, source=source, title=title,
        recipient_user_id=recipient_user_id, entity_type=entity_type, entity_id=entity_id,
        dedupe_key=dedupe_key, notification_type=notification_type, parse_mode=parse_mode,
        button_text=button_text, callback_data=callback_data,
    )
    if row is not None:
        await send_notification_now(bot, session, row)
    return row


async def process_due_telegram_deliveries(bot, db, *, limit: int = 50) -> dict[str, int]:
    """Drain the canonical notifications table with bounded retries."""
    summary = {"sent": 0, "retry": 0, "failed": 0, "processed": 0}
    async with job_lock(db, "notification_center_delivery", ttl_seconds=120) as acquired:
        if not acquired:
            return summary
        now = clock.storage_utc()
        async with db.session_factory() as session:
            rows = list((await session.scalars(
                select(Notification)
                .where(Notification.status.in_(["queued", "retry"]), Notification.scheduled_at <= now)
                .order_by(Notification.scheduled_at.asc(), Notification.id.asc())
                .limit(max(1, int(limit)))
            )).all())
            for row in rows:
                row.last_attempt_at = clock.storage_utc()
                row.updated_at = row.last_attempt_at
                try:
                    await bot.send_message(row.recipient_tg_id, row.body, parse_mode=row.parse_mode, reply_markup=_generic_markup(row))
                    row.status = "sent"
                    row.sent_at = clock.storage_utc()
                    row.error = ""
                    summary["sent"] += 1
                except TelegramForbiddenError as exc:
                    row.error = str(exc)[:500]
                    row.status = "failed"
                    summary["failed"] += 1
                    user = await session.scalar(select(User).where(User.tg_id == row.recipient_tg_id))
                    if user and user.status == UserStatus.ACTIVE.value and user.role in {UserRole.PARTICIPANT.value, UserRole.AMBASSADOR.value}:
                        user.status = UserStatus.DELETED.value
                        user.deleted_at = clock.storage_utc()
                        user.deletion_reason = "TelegramForbiddenError: бот заблоковано або деактивовано"
                        user.restoration_request_status = None
                        from .services import log_audit, revoke_referral_reward_if_inactive
                        await log_audit(session, "telegram_user_auto_deleted", actor_label="system", entity_type="user", entity_id=user.id, details="TelegramForbiddenError: bot blocked/deactivated for this user")
                        revoked = await revoke_referral_reward_if_inactive(session, user, reason="Telegram повідомив, що бот заблоковано/видалено користувачем")
                        if revoked:
                            inviter, removed_xp, days_after = revoked
                            await queue_notification(session, inviter.tg_id, f"🤝 <b>Реферальний бонус скориговано</b>\n\nВаш запрошений учасник <b>{user.full_name}</b> був видалений з активного доступу через {days_after} дн. після активації. Оскільки це сталося протягом 30 днів, скасовано <b>{removed_xp} XP</b> реферального бонусу.", source="referral_clawback", dedupe_key=f"referral_clawback:{user.id}")
                except Exception as exc:
                    next_retry_count = int(row.retry_count or 0) + 1
                    row.retry_count = next_retry_count
                    row.error = str(exc)[:500]
                    if next_retry_count >= int(row.max_attempts or DEFAULT_MAX_ATTEMPTS):
                        row.status = "failed"
                        summary["failed"] += 1
                    else:
                        row.status = "retry"
                        row.scheduled_at = clock.storage_utc() + timedelta(seconds=_retry_delay(next_retry_count))
                        summary["retry"] += 1
                summary["processed"] += 1
                await _sync_legacy_broadcast(session, row)
                await session.commit()
    return summary


async def latest_local_backup(data_dir: str) -> tuple[str | None, datetime | None]:
    root = Path(data_dir) / "backups"
    if not root.exists():
        return None, None
    candidates = [p for p in root.iterdir() if p.is_file()]
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    return latest.name, datetime.utcfromtimestamp(latest.stat().st_mtime)


async def record_backup_marker(db, *, label: str) -> None:
    """Record an externally verified backup and reset bootstrap alert state.

    The marker is written only after the external backup command has completed
    successfully.  Any initial ``unknown`` grace marker is cleared so the UI and
    monitor immediately switch to a verified state.
    """
    now = clock.storage_utc()
    async with db.session_factory() as session:
        row = await session.get(SystemSetting, "last_backup_at")
        value = f"{now.isoformat()}|{label}"
        if row:
            row.value = value
            row.updated_at = now
        else:
            session.add(SystemSetting(key="last_backup_at", value=value, updated_at=now))
        for key in ("monitor.backup.unknown_since", "monitor.backup.last_alert_at"):
            marker = await session.get(SystemSetting, key)
            if marker:
                await session.delete(marker)
        await session.commit()


async def reliability_counts(session) -> dict[str, int]:
    pending_notifications = int(await session.scalar(select(func.count(Notification.id)).where(Notification.status.in_(["queued", "retry"]))) or 0)
    failed_notifications = int(await session.scalar(select(func.count(Notification.id)).where(Notification.status == "failed")) or 0)
    return {"pending_notifications": pending_notifications, "failed_notifications": failed_notifications}


async def notification_failure_alert(bot, db, settings, *, lookback_minutes: int = 30) -> dict[str, int]:
    """Alert superadmins about newly failed Notification Center deliveries.

    Alerts bypass the outbox deliberately: when the outbox itself is unhealthy,
    routing its alert through the same queue would hide the incident. Only
    aggregate counts and notification ids are sent; message bodies/contacts are
    never included.
    """
    now = clock.storage_utc()
    cutoff = now - timedelta(minutes=max(5, int(lookback_minutes)))
    async with db.session_factory() as session:
        marker = await session.get(SystemSetting, "monitor.notifications.last_failed_id")
        try:
            last_id = int(marker.value) if marker and marker.value else 0
        except ValueError:
            last_id = 0
        rows = list((await session.scalars(
            select(Notification).where(
                Notification.status == "failed",
                Notification.id > last_id,
                Notification.updated_at >= cutoff,
            ).order_by(Notification.id.asc()).limit(100)
        )).all())
        if not rows:
            return {"new_failed": 0, "alerted": 0}
        max_id = max(row.id for row in rows)
        types: dict[str, int] = {}
        for row in rows:
            types[row.type or "system"] = types.get(row.type or "system", 0) + 1
        if marker:
            marker.value = str(max_id); marker.updated_at = now
        else:
            session.add(SystemSetting(key="monitor.notifications.last_failed_id", value=str(max_id), updated_at=now))
        await session.commit()

    summary = ", ".join(f"{key}: {value}" for key, value in sorted(types.items()))
    text = (
        "🚨 <b>Notification Center: помилки доставки</b>\n\n"
        f"Нових failed: <b>{len(rows)}</b>\n"
        f"Типи: {summary or 'system'}\n"
        f"Діапазон ID: {rows[0].id}–{max_id}\n\n"
        "Перевірте 🩺 Стан системи → невдалі сповіщення."
    )
    alerted = 0
    for tg_id in sorted(settings.superadmin_ids):
        try:
            await bot.send_message(tg_id, text)
            alerted += 1
        except Exception as exc:
            log.exception(
                "Не вдалося надіслати superadmin alert про Notification Center",
                extra=log_extra("NOTIFICATION_HEALTH_ALERT_FAILED", tg_id=tg_id, exception_type=type(exc).__name__),
            )
    return {"new_failed": len(rows), "alerted": alerted}


async def backup_verification_status(
    session,
    *,
    max_age_hours: int = 168,
    unknown_grace_hours: int = 24,
) -> dict[str, object]:
    """Return the externally verified PostgreSQL backup state.

    ``unknown`` means no verified external backup marker exists yet.  During the
    initial grace window the state is exposed as ``initializing`` instead of
    immediately paging the superadmin.  A successful Heroku/GitHub backup must
    still call ``record_backup_marker``; the grace period never pretends that a
    backup exists.
    """
    row = await session.get(SystemSetting, "last_backup_at")
    if not row or not row.value:
        unknown_row = await session.get(SystemSetting, "monitor.backup.unknown_since")
        if unknown_row and unknown_row.value:
            try:
                unknown_since = datetime.fromisoformat(unknown_row.value)
            except ValueError:
                unknown_since = None
            if unknown_since is not None:
                age = max(0.0, (clock.storage_utc() - unknown_since).total_seconds() / 3600)
                if age < max(1, int(unknown_grace_hours)):
                    remaining = max(0.0, float(unknown_grace_hours) - age)
                    return {
                        "ok": False,
                        "status": "initializing",
                        "verified_at": None,
                        "label": "Очікує першої автоматично підтвердженої копії",
                        "age_hours": None,
                        "grace_remaining_hours": round(remaining, 1),
                    }
        return {
            "ok": False,
            "status": "unknown",
            "verified_at": None,
            "label": "",
            "age_hours": None,
            "grace_remaining_hours": 0.0,
        }
    raw, _, label = row.value.partition("|")
    try:
        verified_at = datetime.fromisoformat(raw)
    except ValueError:
        return {
            "ok": False,
            "status": "invalid",
            "verified_at": None,
            "label": label,
            "age_hours": None,
            "grace_remaining_hours": 0.0,
        }
    age = max(0.0, (clock.storage_utc() - verified_at).total_seconds() / 3600)
    return {
        "ok": age <= max_age_hours,
        "status": "ok" if age <= max_age_hours else "stale",
        "verified_at": verified_at,
        "label": label,
        "age_hours": round(age, 1),
        "grace_remaining_hours": 0.0,
    }


async def backup_health_alert(
    bot,
    db,
    settings,
    *,
    max_age_hours: int = 168,
    repeat_hours: int = 24,
    unknown_grace_hours: int | None = None,
) -> dict[str, object]:
    """Warn superadmins only for a genuinely missing/stale verified backup.

    A fresh deployment without a ``last_backup_at`` marker gets an initial grace
    window instead of an immediate false-positive alarm.  The monitor records
    when the unknown state started; if no verified backup appears before the
    grace expires, the normal alert is sent.  Stale/invalid verified markers are
    never suppressed by this bootstrap grace.
    """
    now = clock.storage_utc()
    grace_hours = int(unknown_grace_hours or getattr(settings, "backup_unknown_grace_hours", 24))
    async with db.session_factory() as session:
        status = await backup_verification_status(
            session,
            max_age_hours=max_age_hours,
            unknown_grace_hours=grace_hours,
        )
        if status.get("ok"):
            return {"alerted": 0, **status}

        # First run on an existing deployment with no verification marker: start
        # a grace window, but do not claim that a backup exists and do not page.
        if status.get("status") == "unknown":
            unknown_row = await session.get(SystemSetting, "monitor.backup.unknown_since")
            if not unknown_row or not unknown_row.value:
                if unknown_row:
                    unknown_row.value = now.isoformat()
                    unknown_row.updated_at = now
                else:
                    session.add(SystemSetting(
                        key="monitor.backup.unknown_since",
                        value=now.isoformat(),
                        updated_at=now,
                    ))
                await session.commit()
                return {
                    "alerted": 0,
                    "ok": False,
                    "status": "initializing",
                    "verified_at": None,
                    "label": "Очікує першої автоматично підтвердженої копії",
                    "age_hours": None,
                    "grace_remaining_hours": float(grace_hours),
                }

        if status.get("status") == "initializing":
            return {"alerted": 0, **status}

        marker = await session.get(SystemSetting, "monitor.backup.last_alert_at")
        if marker and marker.value:
            try:
                last_alert = datetime.fromisoformat(marker.value)
            except ValueError:
                last_alert = None
            if last_alert and now - last_alert < timedelta(hours=max(1, repeat_hours)):
                return {"alerted": 0, **status}
        if marker:
            marker.value = now.isoformat(); marker.updated_at = now
        else:
            session.add(SystemSetting(key="monitor.backup.last_alert_at", value=now.isoformat(), updated_at=now))
        await session.commit()

    age = status.get("age_hours")
    age_text = f"{age} год" if age is not None else "немає підтвердженої копії"
    state_labels = {
        "unknown": "немає підтвердженої копії",
        "stale": "підтверджена копія застаріла",
        "invalid": "пошкоджений маркер перевірки",
    }
    state_text = state_labels.get(str(status.get("status")), "потребує перевірки")
    text = (
        "⚠️ <b>Резервна копія потребує перевірки</b>\n\n"
        f"Стан: <b>{state_text}</b>\n"
        f"Вік останньої підтвердженої копії: <b>{age_text}</b>\n\n"
        "Автоматичний GitHub backup має створити Heroku PGBackup і зафіксувати його в АМП. "
        "Якщо автоматизація не спрацювала — запустіть workflow «AMP Verified Backup» вручну."
    )
    alerted = 0
    for tg_id in sorted(settings.superadmin_ids):
        try:
            await bot.send_message(tg_id, text)
            alerted += 1
        except Exception as exc:
            log.exception(
                "Не вдалося надіслати superadmin alert про резервну копію",
                extra=log_extra("BACKUP_HEALTH_ALERT_FAILED", tg_id=tg_id, exception_type=type(exc).__name__),
            )
    return {"alerted": alerted, **status}
