from __future__ import annotations
import asyncio
import logging
from datetime import timedelta
from aiogram import Bot
from sqlalchemy import select
from ..db import Database
from ..engagement import process_goal_rewards, process_expired_content
from ..leagues import refresh_all_streaks
from ..models import ActivityApplication, EventRegistration, Idea, QuestParticipation, Season, SurveyResponse, User, VolunteerTaskParticipation
from ..observability import log_extra
from ..opportunity_matching import queue_pending_match_digests
from ..reliability import job_lock, queue_telegram_delivery
from ..runtime_config import get_runtime_int
from ..runtime_health import scheduler_heartbeat
from ..season_history import finalize_season
from ..services import log_audit, process_event_operations, revoke_referral_reward_if_inactive
from ..time_utils import clock

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
            log.exception("Помилка планувальника серій", extra=log_extra("SCHED_STREAK_FAILED", scheduler="streak_scheduler", exception_type=type(exc).__name__))
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
            log.exception("Помилка планувальника цілей", extra=log_extra("SCHED_GOAL_REWARD_FAILED", scheduler="goal_reward_scheduler", exception_type=type(exc).__name__))
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
                    now = clock.storage_utc()
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
            log.exception("Помилка планувальника неактивності", extra=log_extra("SCHED_INACTIVITY_FAILED", scheduler="participant_inactivity_scheduler", exception_type=type(exc).__name__))
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
            log.exception("Smart opportunities scheduler failed", extra=log_extra("SCHED_SMART_OPPORTUNITIES_FAILED", scheduler="smart_opportunities_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(900)

async def _season_history_scheduler(bot: Bot, db: Database) -> None:
    """Freeze ended seasons into immutable-ish history snapshots."""
    log = logging.getLogger("amp.season_history")
    while True:
        await scheduler_heartbeat(db, "season_history_scheduler")
        try:
            async with job_lock(db, "season_history_finalize", ttl_seconds=3300) as acquired:
                if acquired:
                    today = clock.today_local()
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
            log.exception("Season history scheduler failed", extra=log_extra("SCHED_SEASON_HISTORY_FAILED", scheduler="season_history_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(3600)

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
        except Exception as exc:
            log.exception("Помилка автоматичного оновлення статусів контенту", extra=log_extra("SCHED_CONTENT_LIFECYCLE_FAILED", scheduler="content_lifecycle_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(300)
