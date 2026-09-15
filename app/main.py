from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from .config import get_settings
from .db import Database
from .engagement import process_goal_rewards, process_expired_content
from .leagues import refresh_all_streaks
from .handlers import admin, donations, events, feedback, participant, quests, start, surveys, v11
from .models import User, Event, EventFeedback, EventRegistration, Notification, QuestParticipation, VolunteerTaskParticipation, ActivityApplication, SurveyResponse, Idea, SystemSetting, UserStatus, Season
from .keyboards import MAIN_MENU_TEXTS
from .services import bootstrap_defaults, get_user_by_tg, process_birthdays, process_expired_bans, process_event_operations, log_audit, revoke_referral_reward_if_inactive
from .reliability import job_lock, process_due_telegram_deliveries, queue_telegram_delivery, queue_notification, notification_failure_alert, backup_health_alert
from .runtime_health import heartbeat_loop, scheduler_heartbeat, supervise_scheduler
from .opportunity_matching import queue_pending_match_digests
from .donations import sync_monobank_donations
from .season_history import finalize_season
from .runtime_config import get_runtime_int




class FSMNavigationMiddleware(BaseMiddleware):
    """Protect multi-step forms from reply-menu text and confirm navigation.

    A reply-keyboard button must never become the answer to the current FSM
    question.  When a form is open, the requested destination is kept inside
    FSM data and the user receives a Yes/No confirmation.  "No" preserves the
    exact form state; "Yes" clears it and opens the requested section.
    """
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            text = (event.text or "").strip()
            state = data.get("state")
            current_state = await state.get_state() if state else None
            if current_state and text in MAIN_MENU_TEXTS:
                await state.update_data(_pending_navigation=text)
                b = InlineKeyboardBuilder()
                b.button(text="✅ Так, перейти", callback_data="fsmnav:yes")
                b.button(text="↩️ Ні, продовжити", callback_data="fsmnav:no")
                b.adjust(1)
                await event.answer(
                    f"⚠️ <b>Ви точно хочете перейти до «{text}»?</b>\n\n"
                    "Незавершена форма залишиться відкритою, якщо обрати «Ні». "
                    "Якщо обрати «Так» — поточне заповнення буде скасовано.",
                    reply_markup=b.as_markup(),
                )
                return None
            is_command = text.startswith(("/start", "/menu", "/help", "/myqr", "/invite", "/cancel"))
            if current_state and is_command:
                await state.clear()
        return await handler(event, data)


class TemporaryBanMiddleware(BaseMiddleware):
    """Block Telegram interactions for temporarily/permanently blocked profiles.

    /start and /help remain available so a user can see their restriction and
    contact information; expired temporary bans are automatically cleared by
    get_user_by_tg().
    """
    async def __call__(self, handler, event, data):
        db = data.get("db")
        from_user = getattr(event, "from_user", None)
        if not db or not from_user:
            return await handler(event, data)
        async with db.session_factory() as session:
            user = await get_user_by_tg(session, from_user.id)
        if not user or user.status != "blocked":
            return await handler(event, data)

        if isinstance(event, Message):
            text = (event.text or "").strip().lower()
            if text.startswith("/start") or text.startswith("/help"):
                return await handler(event, data)
            until = f" до {user.blocked_until.strftime('%d.%m.%Y %H:%M')}" if user.blocked_until else ""
            reason = f"\nПричина: {user.block_reason}" if user.block_reason else ""
            await event.answer(f"⛔ Доступ до функцій АМП тимчасово обмежено{until}.{reason}")
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔ Доступ тимчасово обмежено. Відкрийте /start для деталей.", show_alert=True)
        return None


class DeletedAccountMiddleware(BaseMiddleware):
    """Hard-gate soft-deleted participant profiles while preserving /start restoration flow."""
    async def __call__(self, handler, event, data):
        db=data.get("db"); from_user=getattr(event,"from_user",None)
        if not db or not from_user:
            return await handler(event,data)
        async with db.session_factory() as session:
            user=await get_user_by_tg(session,from_user.id)
        if not user or user.status not in {"deleted","deleted_permanent"}:
            return await handler(event,data)
        state=data.get("state")
        current_state=await state.get_state() if state else None
        if current_state and current_state.startswith("RestorationState:") and user.status=="deleted":
            return await handler(event,data)
        if isinstance(event,Message):
            text=(event.text or "").strip().lower()
            if text.startswith("/start"):
                return await handler(event,data)
            await event.answer("🗑 Доступ до функцій закрито. Відкрийте /start для інформації про статус акаунта та можливість відновлення.")
        elif isinstance(event,CallbackQuery):
            if user.status=="deleted" and (event.data or "").startswith("restore:"):
                return await handler(event,data)
            await event.answer("Доступ до цього акаунта закрито. Відкрийте /start.",show_alert=True)
        return None


class LastActivityMiddleware(BaseMiddleware):
    """Persist the latest Telegram interaction for communication targeting."""
    async def __call__(self, handler, event, data):
        db = data.get("db")
        from_user = getattr(event, "from_user", None)
        if db and from_user:
            try:
                async with db.session_factory() as session:
                    user = await session.scalar(select(User).where(User.tg_id == from_user.id))
                    if user and user.status == "active":
                        user.last_activity_at = datetime.utcnow()
                        await session.commit()
            except Exception:
                logging.getLogger("amp.activity").exception("Не вдалося оновити last_activity_at")
        return await handler(event, data)


async def _birthday_scheduler(bot: Bot, db: Database, settings) -> None:
    """Award birthdays once and queue Telegram delivery with durable retry."""
    log = logging.getLogger("amp.birthdays")
    tz = ZoneInfo(settings.timezone or "Europe/Kyiv")
    while True:
        await scheduler_heartbeat(db, "birthday_scheduler")
        now = datetime.now(tz)
        today_nine = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now < today_nine:
            await asyncio.sleep(max(1, (today_nine - now).total_seconds()))
            now = datetime.now(tz)
        try:
            async with job_lock(db, "birthday_rewards", ttl_seconds=3300) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        await process_expired_bans(session, datetime.utcnow())
                        rewarded = await process_birthdays(session, now.date())
                        for tg_id, first_name, amount in rewarded:
                            await queue_telegram_delivery(
                                session,
                                tg_id,
                                f"🎉 <b>З днем народження, {first_name}!</b>\n\n"
                                "Команда АМПасадорів бажає тобі сил, натхнення, крутих людей поруч і сміливих ідей 🚀\n\n"
                                f"🎁 До твого профілю автоматично нараховано <b>+{amount} XP</b> як подарунок від АМП.\n"
                                "Нехай цей рік відкриє ще більше можливостей! 💙",
                                source="birthday",
                                dedupe_key=f"birthday:{tg_id}:{now.date().year}",
                            )
                        await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка перевірки днів народження: %s", exc)
        await asyncio.sleep(3600)



async def _event_reminder_scheduler(bot: Bot, db: Database, settings) -> None:
    """Queue one reminder using the runtime-configured lead time."""
    log = logging.getLogger("amp.event_reminders")
    tz = ZoneInfo(settings.timezone or "Europe/Kyiv")
    while True:
        await scheduler_heartbeat(db, "event_reminder_scheduler")
        try:
            async with job_lock(db, "event_reminders", ttl_seconds=240) as acquired:
                if acquired:
                    local_now = datetime.now(tz).replace(tzinfo=None)
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
                                f"📍 {event.location or 'АМП'}\n\nДо зустрічі 💙",
                                source="event_reminder",
                                dedupe_key=f"event_reminder:{reg.id}",
                            )
                            # Mark as queued. Delivery status is tracked separately
                            # and transient failures are retried by the outbox worker.
                            reg.reminder_1h_sent_at = datetime.utcnow()
                        if rows:
                            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка планувальника нагадувань про події: %s", exc)
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
                    now = datetime.utcnow()
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
                            except Exception:
                                feature_started = now
                            rows = (await session.execute(
                                select(EventRegistration, Event, User)
                                .join(Event, Event.id == EventRegistration.event_id)
                                .join(User, User.id == EventRegistration.user_id)
                                .where(
                                    EventRegistration.status == "attended",
                                    Event.starts_at >= feature_started - timedelta(hours=6),
                                    Event.starts_at <= now,
                                    User.status == UserStatus.ACTIVE.value,
                                )
                                .order_by(Event.starts_at.asc())
                            )).all()
                            for reg, event, user in rows:
                                # Feedback is sent roughly 2 hours after the participant's
                                # confirmed attendance (or event start when confirmation time
                                # is unavailable). This keeps the questionnaire post-event and
                                # avoids asking while a typical activity is still running.
                                anchor = reg.confirmed_at or event.starts_at
                                if not anchor or anchor + timedelta(minutes=feedback_delay_minutes) > now:
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
            log.exception("Помилка планувальника зворотного зв’язку після подій: %s", exc)
        await asyncio.sleep(900)


async def _streak_scheduler(bot: Bot, db: Database) -> None:
    """Refresh streak state once per lease and queue earned-badge notices."""
    log = logging.getLogger("amp.streaks")
    while True:
        await scheduler_heartbeat(db, "streak_scheduler")
        try:
            async with job_lock(db, "streak_refresh", ttl_seconds=840) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        badge_days = await get_runtime_int(session, "streak.badge_days")
                        notices = await refresh_all_streaks(session)
                        for tg_id, _ in notices:
                            await queue_telegram_delivery(
                                session,
                                tg_id,
                                f"🔥 <b>Суперсерія — {badge_days}+ днів!</b>\n\n"
                                f"Ти тримаєш серію відвідування подій уже щонайменше {badge_days} днів. "
                                "До профілю додано спеціальний бейдж 🏅",
                                source="streak_badge",
                                dedupe_key=f"streak_badge_30d:{tg_id}",
                            )
                        await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка планувальника серій: %s", exc)
        await asyncio.sleep(900)



async def _goal_reward_scheduler(bot: Bot, db: Database) -> None:
    """Award configured mission XP once and queue reliable notifications."""
    log = logging.getLogger("amp.goal_rewards")
    while True:
        await scheduler_heartbeat(db, "goal_reward_scheduler")
        try:
            async with job_lock(db, "goal_rewards", ttl_seconds=240) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        notices = await process_goal_rewards(session)
                        for tg_id, title, reward_xp in notices:
                            await queue_telegram_delivery(
                                session,
                                tg_id,
                                f"🏁 <b>Ціль виконано!</b>\n\n«<b>{title}</b>»\n"
                                f"🎁 Нараховано <b>+{reward_xp} XP</b>. Вітаємо! 🚀",
                                source="goal_reward",
                                dedupe_key=f"goal_reward:{tg_id}:{title}:{reward_xp}",
                            )
                        if notices:
                            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка планувальника цілей: %s", exc)
        await asyncio.sleep(300)



async def _inactivity_scheduler(bot: Bot, db: Database) -> None:
    """Warn and soft-remove inactive participant accounts after 60 days.

    We intentionally keep historical rows for reports/audit and switch the
    profile to ``deleted`` instead of physically deleting relational data. A recoverable
    deletion can be restored only through the superadmin restoration workflow.
    Blocked profiles and staff roles are never processed by this rule.
    """
    log = logging.getLogger("amp.inactivity")
    while True:
        await scheduler_heartbeat(db, "participant_inactivity_scheduler")
        try:
            async with job_lock(db, "participant_inactivity", ttl_seconds=3300) as acquired:
                if acquired:
                    now = datetime.utcnow()
                    cutoff_55 = now - timedelta(days=55)
                    cutoff_59 = now - timedelta(days=59)
                    cutoff_60 = now - timedelta(days=60)
                    async with db.session_factory() as session:
                        users = list((await session.scalars(
                            select(User).where(
                                User.status == "active",
                                User.role.in_(["participant", "ambassador"]),
                            )
                        )).all())
                        changed = 0
                        for user in users:
                            anchor = user.last_activity_at or user.created_at
                            due_date = (anchor + timedelta(days=60)).date().isoformat()
                            if anchor <= cutoff_60:
                                user.status = "deleted"
                                user.deleted_at = now
                                user.deletion_reason = "60 днів без активності"
                                user.restoration_request_status = None
                                await log_audit(
                                    session, "user_auto_deleted_60d", actor_label="system",
                                    entity_type="user", entity_id=user.id,
                                    details=f"60 днів без активності; last_activity_at={anchor.isoformat()}",
                                )
                                revoked = await revoke_referral_reward_if_inactive(
                                    session, user, reason="Автоматичне видалення доступу після 60 днів без взаємодії"
                                )
                                await queue_telegram_delivery(
                                    session, user.tg_id,
                                    "🗑 <b>Ваш акаунт АМПасадорів видалено з активного доступу</b>\n\n"
                                    "Минуло 60 днів без активності, тому доступ до функцій бота закрито. "
                                    "Ваші дані, XP та історія участі збережені. Відкрийте /start, щоб подати запит на відновлення.",
                                    source="inactivity", dedupe_key=f"inactivity:deleted:{user.id}:{due_date}",
                                )
                                if revoked:
                                    inviter, removed_xp, days_after = revoked
                                    await queue_telegram_delivery(
                                        session, inviter.tg_id,
                                        f"🤝 <b>Реферальний бонус скориговано</b>\n\n"
                                        f"Запрошений учасник <b>{user.full_name}</b> був автоматично видалений з активного доступу. "
                                        f"Скасовано <b>{removed_xp} XP</b> відповідно до правила 30 днів.",
                                        source="referral_clawback", dedupe_key=f"referral_clawback:{user.id}",
                                    )
                                changed += 1
                            elif anchor <= cutoff_59:
                                await queue_telegram_delivery(
                                    session, user.tg_id,
                                    "⚠️ <b>До автоматичного закриття профілю залишився 1 день</b>\n\n"
                                    "Якщо ви не проявите активність у боті, акаунт буде видалено з активного доступу, а доступ до бота буде закрито. "
                                    "Просто скористайтеся будь-якою функцією АМПасадорів, щоб оновити активність.",
                                    source="inactivity_warning", dedupe_key=f"inactivity:warn1:{user.id}:{due_date}",
                                )
                            elif anchor <= cutoff_55:
                                await queue_telegram_delivery(
                                    session, user.tg_id,
                                    "⚠️ <b>Нагадування про активність</b>\n\n"
                                    "Через 5 днів без активності ваш акаунт буде автоматично видалено з активного доступу та доступ до бота буде закрито. "
                                    "Скористайтеся будь-якою функцією АМПасадорів, щоб залишитися активним учасником.",
                                    source="inactivity_warning", dedupe_key=f"inactivity:warn5:{user.id}:{due_date}",
                                )
                        # 14-денний випробувальний строк після відновлення.
                        restored_users = list((await session.scalars(
                            select(User).where(
                                User.status == "active",
                                User.probation_until.is_not(None),
                                User.probation_until <= now,
                            )
                        )).all())
                        for restored in restored_users:
                            since = restored.probation_started_at or restored.restored_at or restored.probation_until - timedelta(days=14)
                            participated = False
                            if await session.scalar(select(EventRegistration.id).where(EventRegistration.user_id==restored.id, EventRegistration.status=="attended", EventRegistration.confirmed_at>=since).limit(1)):
                                participated = True
                            if not participated and await session.scalar(select(QuestParticipation.id).where(QuestParticipation.user_id==restored.id, QuestParticipation.status=="approved", QuestParticipation.approved_at>=since).limit(1)):
                                participated = True
                            if not participated and await session.scalar(select(VolunteerTaskParticipation.id).where(VolunteerTaskParticipation.user_id==restored.id, VolunteerTaskParticipation.status=="approved", VolunteerTaskParticipation.approved_at>=since).limit(1)):
                                participated = True
                            if not participated and await session.scalar(select(ActivityApplication.id).where(ActivityApplication.user_id==restored.id, ActivityApplication.status=="activity_completed", ActivityApplication.completed_at>=since).limit(1)):
                                participated = True
                            if not participated and await session.scalar(select(SurveyResponse.id).where(SurveyResponse.user_id==restored.id, SurveyResponse.completed_at>=since).limit(1)):
                                participated = True
                            if not participated and await session.scalar(select(Idea.id).where(Idea.user_id==restored.id, Idea.created_at>=since).limit(1)):
                                participated = True
                            if participated:
                                restored.probation_until = None
                                restored.probation_started_at = None
                                await log_audit(session, "restoration_probation_passed", actor_label="system", entity_type="user", entity_id=restored.id, details="Є підтверджена участь протягом 14 днів після відновлення")
                                await queue_telegram_delivery(session, restored.tg_id, "✅ <b>Випробувальний строк пройдено</b>\n\nДякуємо за активність! Ваш акаунт залишається активним без обмежень.", source="restoration", dedupe_key=f"restoration:passed:{restored.id}:{since.date().isoformat()}")
                            else:
                                restored.status = "deleted_permanent"
                                restored.permanent_deleted_at = now
                                restored.deleted_at = restored.deleted_at or now
                                restored.deletion_reason = "Не було підтвердженої участі протягом 14-денного випробувального строку після відновлення"
                                restored.restoration_request_status = "closed"
                                restored.probation_until = None
                                await log_audit(session, "user_auto_deleted_permanent_probation", actor_label="system", entity_type="user", entity_id=restored.id, details="14 днів після відновлення без підтвердженої участі")
                                await queue_telegram_delivery(session, restored.tg_id, "⛔ <b>Акаунт видалено без можливості відновлення</b>\n\nПісля відновлення протягом 14-денного випробувального строку не було зафіксовано підтвердженої участі в активностях АМП. Дані та історія участі збережені, але доступ закрито назавжди.", source="restoration", dedupe_key=f"restoration:permanent:{restored.id}:{since.date().isoformat()}")
                        await session.commit()
                        if changed:
                            log.info("Auto-deleted %s inactive participant accounts", changed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка планувальника неактивності: %s", exc)
        await asyncio.sleep(3600)


async def _smart_opportunities_scheduler(bot: Bot, db: Database) -> None:
    """Create compact personalized opportunity digests without profiling vulnerability data."""
    log = logging.getLogger("amp.smart_opportunities")
    while True:
        await scheduler_heartbeat(db, "smart_opportunities_scheduler")
        try:
            async with job_lock(db, "smart_opportunities", ttl_seconds=840) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        queued = await queue_pending_match_digests(session, max_items=3)
                        await session.commit()
                        if queued:
                            log.info("Queued %s personalized opportunity digests", queued)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Smart opportunities scheduler failed: %s", exc)
        await asyncio.sleep(900)


async def _season_history_scheduler(bot: Bot, db: Database) -> None:
    """Freeze ended seasons into immutable-ish history snapshots."""
    log = logging.getLogger("amp.season_history")
    while True:
        await scheduler_heartbeat(db, "season_history_scheduler")
        try:
            async with job_lock(db, "season_history_finalize", ttl_seconds=3300) as acquired:
                if acquired:
                    today = datetime.utcnow().date()
                    async with db.session_factory() as session:
                        ended = list((await session.scalars(select(Season).where(
                            Season.ends_at < today,
                            Season.finalized_at.is_(None),
                        ))).all())
                        for season in ended:
                            await finalize_season(session, season)
                        await session.commit()
                        if ended:
                            log.info("Finalized %s ended seasons", len(ended))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Season history scheduler failed: %s", exc)
        await asyncio.sleep(3600)


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
            log.exception("Помилка retry-планувальника Telegram: %s", exc)
        await asyncio.sleep(15)


async def _donation_sync_scheduler(bot: Bot, db: Database, settings) -> None:
    """Refresh the configured Monobank jar every five minutes.

    A database lock keeps web/bot dynos from racing if this scheduler is moved
    to more than one worker later. Monobank's statement API is intentionally
    not polled more frequently.
    """
    log = logging.getLogger("amp.donations")
    while True:
        await scheduler_heartbeat(db, "donation_sync_scheduler")
        try:
            if settings.monobank_token:
                async with job_lock(db, "monobank_donations_sync", ttl_seconds=240) as acquired:
                    if acquired:
                        async with db.session_factory() as session:
                            result = await sync_monobank_donations(session, settings)
                            if result.get("ok"):
                                log.info("Donations sync: imported=%s linked=%s", result.get("imported", 0), result.get("linked", 0))
                            else:
                                log.warning("Donations sync failed: %s", result.get("error"))
                            for user_id, badge_names in (result.get("awarded") or {}).items():
                                user = await session.get(User, int(user_id))
                                if not user or not user.tg_id:
                                    continue
                                await queue_telegram_delivery(
                                    session,
                                    user.tg_id,
                                    "💙 <b>Дякуємо за підтримку АМП!</b>\n\n" + "🏅 Нові бейджі: " + ", ".join(badge_names),
                                    source="donation_badge",
                                    notification_type="gamification",
                                    recipient_user_id=user.id,
                                    entity_type="user",
                                    entity_id=user.id,
                                    dedupe_key=f"donation_badges:{user.id}:{':'.join(sorted(badge_names))}",
                                )
                            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка синхронізації донатів: %s", exc)
        await asyncio.sleep(300)


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
        except Exception:
            log.exception("Помилка моніторингу failed Notification Center")
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
        except Exception:
            log.exception("Помилка перевірки резервних копій")
        await asyncio.sleep(6 * 3600)


async def _content_lifecycle_scheduler(db: Database) -> None:
    """Move deadline/status housekeeping to the worker process.

    Web requests still perform a lightweight refresh when relevant pages are
    opened, preserving v1.11 behavior if the worker is temporarily unavailable.
    """
    log = logging.getLogger("amp.content_lifecycle")
    while True:
        await scheduler_heartbeat(db, "content_lifecycle_scheduler")
        try:
            async with job_lock(db, "content_lifecycle", ttl_seconds=240) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        changed = await process_expired_content(session)
                        event_ops = await process_event_operations(session)
                        combined = dict(changed)
                        for key, value in event_ops.items():
                            if value:
                                combined[key] = combined.get(key, 0) + int(value)
                        if combined:
                            await log_audit(
                                session, "system_auto_complete", actor_label="Система АМП",
                                entity_type="system", details=str(combined),
                            )
                            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Помилка автоматичного оновлення статусів контенту")
        await asyncio.sleep(300)


async def main() -> None:
    settings = get_settings()

    # Keep SQLite data directory available when using the default URL.
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    db = Database(settings)
    await db.init()
    await bootstrap_defaults(db, settings)

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.set_my_name(name="АМПасадори")
        await bot.set_my_short_description(short_description="Активності, XP, квести, волонтерство та можливості АМП.")
        await bot.set_my_description(description="Офіційний бот волонтерської групи «АМПасадори» Анисівського молодіжного простору: події, опитування, квести, досвід, винагороди та волонтерські задачі.")
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустити бота / реєстрація"),
            BotCommand(command="menu", description="Головне меню"),
            BotCommand(command="help", description="Довідка та QR"),
            BotCommand(command="myqr", description="Мій персональний QR-бейдж"),
            BotCommand(command="invite", description="Запросити друга"),
            BotCommand(command="cancel", description="Скасувати незавершену дію"),
        ])
    except Exception:
        logging.getLogger(__name__).warning("Не вдалося оновити публічний опис бота")
    dp = Dispatcher()
    activity_tracker = LastActivityMiddleware()
    ban_guard = TemporaryBanMiddleware()
    deleted_guard = DeletedAccountMiddleware()
    navigation_guard = FSMNavigationMiddleware()
    dp.message.outer_middleware(navigation_guard)
    dp.message.outer_middleware(activity_tracker)
    dp.callback_query.outer_middleware(activity_tracker)
    dp.message.outer_middleware(ban_guard)
    dp.callback_query.outer_middleware(ban_guard)
    dp.message.outer_middleware(deleted_guard)
    dp.callback_query.outer_middleware(deleted_guard)
    # Navigation routers come before admin FSM handlers so menu buttons always
    # work even if an administrator left an unfinished creation wizard.
    dp.include_router(start.router)
    dp.include_router(v11.router)
    dp.include_router(donations.router)
    dp.include_router(feedback.router)
    dp.include_router(surveys.router)
    dp.include_router(participant.router)
    dp.include_router(events.router)
    dp.include_router(quests.router)
    dp.include_router(admin.router)

    async def _open_confirmed_navigation(call: CallbackQuery, target: str, state) -> None:
        # Reuse the normal participant handlers so a confirmed transition opens
        # the destination immediately instead of asking the user to tap twice.
        msg = call.message.model_copy(update={"from_user": call.from_user, "text": target})
        mapping = {
            "🏠 Головна": lambda: participant.overview(msg, db),
            "🏠 Огляд": lambda: participant.overview(msg, db),
            "🚀 Долучитися": lambda: participant.join_hub(msg, db),
            "☰ Ще": lambda: participant.more_hub(msg, db),
            "👤 Мій профіль": lambda: participant.profile(msg, db),
            "📈 Сезон": lambda: v11.season_profile(msg, db),
            "📅 Події": lambda: events.list_events(msg, db),
            "⚡ Активності": lambda: participant.activity_catalog(msg, db),
            "🎯 Квести": lambda: quests.list_quests(msg, db),
            "✅ Волонтерство": lambda: participant.tasks(msg, db),
            "✅ Волонтерські задачі": lambda: participant.tasks(msg, db),
            "🏅 Бейджі": lambda: participant.badges(msg, db),
            "🎁 Винагороди": lambda: participant.rewards(msg, db),
            "🎫 QR-бейдж": lambda: v11.my_qr(msg, db, state),
            "🎫 Мій QR-бейдж": lambda: v11.my_qr(msg, db, state),
            "🎫 Мій QR-код": lambda: v11.my_qr(msg, db, state),
            "🤝 Запросити друга": lambda: v11.invite_friend(msg, db, bot),
            "📊 Рейтинг": lambda: participant.leaderboard(msg, db),
            "🔥 Серії участі": lambda: participant.streaks_menu(msg, db, state),
            "🏁 Цілі & місії": lambda: participant.participant_goals(msg, db),
            "💡 Нова ідея": lambda: participant.idea_start(msg, state),
            "💡 Запропонувати ідею": lambda: participant.idea_start(msg, state),
            "🌍 Можливості": lambda: participant.opportunities(msg, db),
            "📰 Можливості": lambda: participant.opportunities(msg, db),
            "🆘 Звернення": lambda: participant.request_menu(msg, state),
            "📋 Опитування": lambda: surveys.surveys_menu(msg, db, state),
            "📜 Правила": lambda: participant.rules(msg),
            "🛠 Адмін-панель": lambda: admin.admin_panel(msg, db),
        }
        action = mapping.get(target)
        if action:
            await action()
        else:
            await call.message.answer(f"✅ Перехід до «{target}» підтверджено.")

    @dp.callback_query(F.data.in_({"fsmnav:yes", "fsmnav:no"}))
    async def confirm_fsm_navigation(call: CallbackQuery, state) -> None:
        data = await state.get_data()
        target = str(data.get("_pending_navigation") or "")
        if call.data == "fsmnav:no":
            data.pop("_pending_navigation", None)
            await state.set_data(data)
            await call.answer("Продовжуємо заповнення")
            try:
                await call.message.edit_text("↩️ Добре, продовжуємо заповнення поточної форми.")
            except Exception:
                pass
            return
        await state.clear()
        await call.answer("Перехід підтверджено")
        try:
            await call.message.edit_text(f"✅ Перехід до «{target}» підтверджено.")
        except Exception:
            pass
        if target:
            await _open_confirmed_navigation(call, target, state)

    @dp.callback_query(F.data.startswith("ux:"))
    async def participant_ux_navigation(call: CallbackQuery, state) -> None:
        """Second-level participant navigation for the compact v1.10.0 menu."""
        action = str(call.data or "")
        msg = call.message.model_copy(update={"from_user": call.from_user, "text": ""})
        await state.clear()
        mapping = {
            "ux:join:events": lambda: events.list_events(msg, db),
            "ux:join:quests": lambda: quests.list_quests(msg, db),
            "ux:join:volunteer": lambda: participant.tasks(msg, db),
            "ux:join:activities": lambda: participant.activity_catalog(msg, db),
            "ux:join:ideas": lambda: participant.idea_start(msg, state),
            "ux:join:surveys": lambda: surveys.surveys_menu(msg, db, state),
            "ux:mine:profile": lambda: participant.profile(msg, db),
            "ux:mine:xp": lambda: participant.xp_history(msg, db),
            "ux:mine:league": lambda: v11.season_profile(msg, db),
            "ux:mine:streaks": lambda: participant.streaks_menu(msg, db, state),
            "ux:mine:goals": lambda: participant.participant_goals(msg, db),
            "ux:mine:badges": lambda: participant.badges(msg, db),
            "ux:mine:rewards": lambda: participant.rewards(msg, db),
            "ux:mine:invite": lambda: v11.invite_friend(msg, db, bot),
            "ux:more:requests": lambda: participant.request_menu(msg, state),
            "ux:more:rules": lambda: participant.rules(msg),
            "ux:more:help": lambda: start.help_command(msg),
        }
        if action == "ux:mine:seasons":
            await v11.season_history(call, db)
            return
        fn = mapping.get(action)
        if not fn:
            await call.answer("Розділ недоступний", show_alert=True)
            return
        await call.answer()
        await fn()


    @dp.callback_query(F.data == "noop")
    async def noop(call: CallbackQuery) -> None:
        await call.answer()

    # v1.12.1: each scheduler runs behind a supervisor. If an infinite
    # scheduler exits unexpectedly, the supervisor records the failure, alerts
    # superadmins directly and restarts it after a short delay. A separate
    # worker heartbeat lets the web process/external monitors detect a dead
    # worker even when Telegram polling itself is no longer running.
    worker_heartbeat_task = asyncio.create_task(
        heartbeat_loop(db, "worker", interval_seconds=settings.worker_heartbeat_seconds, initial_status="running"),
        name="worker_heartbeat",
    )
    scheduler_factories = {
        "birthday_scheduler": lambda: _birthday_scheduler(bot, db, settings),
        "event_reminder_scheduler": lambda: _event_reminder_scheduler(bot, db, settings),
        "event_feedback_scheduler": lambda: _event_feedback_scheduler(bot, db),
        "goal_reward_scheduler": lambda: _goal_reward_scheduler(bot, db),
        "streak_scheduler": lambda: _streak_scheduler(bot, db),
        "notification_retry_scheduler": lambda: _notification_retry_scheduler(bot, db),
        "participant_inactivity_scheduler": lambda: _inactivity_scheduler(bot, db),
        "smart_opportunities_scheduler": lambda: _smart_opportunities_scheduler(bot, db),
        "season_history_scheduler": lambda: _season_history_scheduler(bot, db),
        "donation_sync_scheduler": lambda: _donation_sync_scheduler(bot, db, settings),
        "notification_health_scheduler": lambda: _notification_health_scheduler(bot, db, settings),
        "backup_health_scheduler": lambda: _backup_health_scheduler(bot, db, settings),
        "content_lifecycle_scheduler": lambda: _content_lifecycle_scheduler(db),
    }
    scheduler_tasks = [
        asyncio.create_task(
            supervise_scheduler(name, factory, db=db, bot=bot, settings=settings),
            name=f"supervisor:{name}",
        )
        for name, factory in scheduler_factories.items()
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
