from __future__ import annotations
import asyncio
import logging
from aiogram import Bot
from ..db import Database
from ..donations import sync_monobank_donations
from ..model_domains import User
from ..observability import log_extra
from ..reliability import job_lock, queue_telegram_delivery
from ..runtime_health import scheduler_heartbeat

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
                            for user_id, xp_amount in (result.get("xp_awarded") or {}).items():
                                user = await session.get(User, int(user_id))
                                if not user or not user.tg_id or int(xp_amount or 0) <= 0:
                                    continue
                                await queue_telegram_delivery(
                                    session, user.tg_id,
                                    f"💙 <b>Дякуємо за підтримку АМП!</b>\n\n⚡ За донат нараховано <b>+{int(xp_amount)} XP</b>.\nКурс: <b>1 XP = 5 грн</b>.",
                                    source="donation_xp", notification_type="gamification",
                                    recipient_user_id=user.id, entity_type="user", entity_id=user.id,
                                    dedupe_key=f"donation_xp_sync:{user.id}:{int(xp_amount)}:{result.get('imported', 0)}:{result.get('linked', 0)}",
                                )
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
            log.exception("Помилка синхронізації донатів", extra=log_extra("SCHED_DONATION_SYNC_FAILED", scheduler="donation_sync_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(300)
