from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot
from sqlalchemy import select
from ..db import Database
from ..models import Event, EventFeedback, EventRegistration, Notification, SystemSetting, User, UserStatus
from ..observability import log_extra
from ..reliability import job_lock, queue_notification, queue_telegram_delivery
from ..runtime_config import get_runtime_int
from ..runtime_health import scheduler_heartbeat
from ..time_utils import clock

async def _event_reminder_scheduler(bot: Bot, db: Database, settings) -> None:
    """Queue one reminder using the runtime-configured lead time."""
    log = logging.getLogger("amp.event_reminders")
    while True:
        await scheduler_heartbeat(db, "event_reminder_scheduler")
        try:
            async with job_lock(db, "event_reminders", ttl_seconds=240) as acquired:
                if acquired:
                    local_now = clock.local_wall()
                    async with db.session_factory() as session:
                        reminder_minutes = await get_runtime_int(session, "events.reminder_minutes")
                        start = local_now + timedelta(minutes=max(0, reminder_minutes - 5))
                        end = local_now + timedelta(minutes=reminder_minutes + 5)
                        rows = (await session.execute(
                            select(EventRegistration, Event, User)
                            .join(Event, Event.id == EventRegistration.event_id)
                            .join(User, User.id == EventRegistration.user_id)
                            .where(
                                EventRegistration.status.in_(["registered", "reserved", "checked_in"]),
                                EventRegistration.reminder_1h_sent_at.is_(None),
                                Event.status.in_(["open", "postponed"]),
                                Event.starts_at >= start, Event.starts_at <= end,
                                User.status == "active",
                            )
                        )).all()
                        for reg, event, user in rows:
                            await queue_telegram_delivery(
                                session,
                                user.tg_id,
                                f"⏰ <b>Нагадування про подію</b>\n\n"
                                f"До початку «<b>{event.title}</b>» залишилось приблизно <b>{reminder_minutes} хв</b>.\n"
                                f"🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
                                f"📍 {event.location or 'АМП'}\n\n"
                                f"🎟 Якщо прийдеш після попередньої реєстрації: +{int(getattr(event, 'preregistration_bonus_xp', 0) or 0)} бонусних XP.\n"
                                f"🚫 Якщо плани змінилися — скасуй реєстрацію до початку. Неявка без скасування: -{int(getattr(event, 'no_show_penalty_xp', 0) or 0)} XP.\n\n"
                                "До зустрічі 💙",
                                source="event_reminder",
                                dedupe_key=f"event_reminder:{reg.id}",
                            )
                            # Mark as queued. Delivery status is tracked separately
                            # and transient failures are retried by the outbox worker.
                            reg.reminder_1h_sent_at = clock.storage_utc()
                        if rows:
                            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка планувальника нагадувань про події", extra=log_extra("SCHED_EVENT_REMINDER_FAILED", scheduler="event_reminder_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(300)

async def _event_feedback_scheduler(bot: Bot, db: Database) -> None:
    """Ask attended participants for outcome feedback about two hours after events.

    The first run stores a feature-start marker so deploying v1.9.0 does not
    suddenly message participants about old historical events.
    """
    log = logging.getLogger("amp.event_feedback")
    while True:
        await scheduler_heartbeat(db, "event_feedback_scheduler")
        try:
            async with job_lock(db, "event_feedback_scheduler", ttl_seconds=600) as acquired:
                if acquired:
                    now_utc = clock.now_utc()
                    now = clock.storage_utc(now_utc)
                    event_now = clock.local_wall(now_utc)
                    async with db.session_factory() as session:
                        feedback_delay_minutes = await get_runtime_int(session, "events.feedback_delay_minutes")
                        feedback_reminder_hours = await get_runtime_int(session, "events.feedback_reminder_hours")
                        marker = await session.get(SystemSetting, "event_feedback_feature_started_at")
                        if not marker:
                            session.add(SystemSetting(key="event_feedback_feature_started_at", value=now.isoformat(), updated_at=now))
                            await session.commit()
                        else:
                            try:
                                feature_started = datetime.fromisoformat(marker.value)
                                feature_started_utc = clock.from_storage_utc(feature_started) or now_utc
                            except (TypeError, ValueError) as exc:
                                feature_started_utc = now_utc
                                log.warning(
                                    "Некоректний marker старту feedback; використано поточний час",
                                    extra=log_extra("EVENT_FEEDBACK_MARKER_INVALID", exception_type=type(exc).__name__),
                                )
                            feature_started_local = clock.local_wall(feature_started_utc)
                            rows = (await session.execute(
                                select(EventRegistration, Event, User)
                                .join(Event, Event.id == EventRegistration.event_id)
                                .join(User, User.id == EventRegistration.user_id)
                                .where(
                                    EventRegistration.status == "attended",
                                    Event.starts_at >= feature_started_local - timedelta(hours=6),
                                    Event.starts_at <= event_now,
                                    User.status == UserStatus.ACTIVE.value,
                                )
                                .order_by(Event.starts_at.asc())
                            )).all()
                            for reg, event, user in rows:
                                # Feedback is sent roughly 2 hours after the participant's
                                # confirmed attendance (or event start when confirmation time
                                # is unavailable). This keeps the questionnaire post-event and
                                # avoids asking while a typical activity is still running.
                                if reg.confirmed_at:
                                    anchor_utc = clock.from_storage_utc(reg.confirmed_at)
                                else:
                                    anchor_utc = clock.event_utc(event.starts_at)
                                if not anchor_utc or anchor_utc + timedelta(minutes=feedback_delay_minutes) > now_utc:
                                    continue
                                existing = await session.scalar(select(EventFeedback).where(EventFeedback.event_id == event.id, EventFeedback.user_id == user.id))
                                if existing:
                                    continue
                                fb = EventFeedback(event_id=event.id, user_id=user.id, status="pending", prompted_at=now, created_at=now, updated_at=now)
                                session.add(fb)
                                await session.flush()
                                await queue_notification(
                                    session, user.tg_id,
                                    f"⭐ <b>Як оціниш подію «{event.title}»?</b>\n\nОбери оцінку від 1 до 5. Це займе менше хвилини та допоможе АМП покращувати наступні активності.",
                                    source="event_feedback",
                                    notification_type="event",
                                    title=f"Відгук: {event.title}",
                                    recipient_user_id=user.id,
                                    entity_type="event_feedback_rating", entity_id=fb.id,
                                    dedupe_key=f"event_feedback:prompt:{event.id}:{user.id}",
                                )

                            # Feedback 2.0: one reminder only. Dedupe guarantees that a
                            # restart or a second scheduler process cannot send it twice.
                            reminder_before = now - timedelta(hours=feedback_reminder_hours)
                            reminder_rows = (await session.execute(
                                select(EventFeedback, Event, User)
                                .join(Event, Event.id == EventFeedback.event_id)
                                .join(User, User.id == EventFeedback.user_id)
                                .where(
                                    EventFeedback.status.in_(["pending", "in_progress"]),
                                    EventFeedback.prompted_at.is_not(None),
                                    EventFeedback.prompted_at <= reminder_before,
                                    User.status == UserStatus.ACTIVE.value,
                                )
                                .order_by(EventFeedback.prompted_at.asc())
                            )).all()
                            for fb, event, user in reminder_rows:
                                initial_delivery = await session.scalar(select(Notification).where(
                                    Notification.dedupe_key == f"event_feedback:prompt:{event.id}:{user.id}"
                                ))
                                # If the first prompt is still queued/retrying, let the
                                # durable outbox finish that delivery instead of creating
                                # a second user-facing message.
                                if not initial_delivery or initial_delivery.status != "sent":
                                    continue
                                if fb.rating is None:
                                    entity_type, question = "event_feedback_rating", "Обери оцінку від 1 до 5."
                                elif fb.useful is None:
                                    entity_type, question = "event_feedback_useful", "Було корисно?"
                                elif fb.new_knowledge is None:
                                    entity_type, question = "event_feedback_knowledge", "Дізнався/дізналася щось нове?"
                                elif fb.felt_safe is None:
                                    entity_type, question = "event_feedback_safe", "Почувався/почувалася безпечно?"
                                elif fb.would_return is None:
                                    entity_type, question = "event_feedback_return", "Хочеш прийти на події АМП ще?"
                                else:
                                    fb.status = "completed"
                                    fb.completed_at = fb.completed_at or now
                                    fb.updated_at = now
                                    continue
                                await queue_notification(
                                    session, user.tg_id,
                                    f"🔔 <b>Коротке нагадування про відгук</b>\n\n"
                                    f"Про подію «{event.title}» залишилося кілька натискань. {question}",
                                    source="event_feedback_reminder",
                                    notification_type="event",
                                    title=f"Нагадування про відгук: {event.title}",
                                    recipient_user_id=user.id,
                                    entity_type=entity_type, entity_id=fb.id,
                                    dedupe_key=f"event_feedback:reminder:{fb.id}",
                                )
                            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка планувальника зворотного зв’язку після подій", extra=log_extra("SCHED_EVENT_FEEDBACK_FAILED", scheduler="event_feedback_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(900)
