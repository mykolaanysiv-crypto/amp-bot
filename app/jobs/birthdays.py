from __future__ import annotations
import asyncio
import logging
from aiogram import Bot
from ..db import Database
from ..observability import log_extra
from ..reliability import job_lock, queue_telegram_delivery
from ..runtime_health import scheduler_heartbeat
from ..services import process_birthdays, process_expired_bans
from ..time_utils import clock

async def _birthday_scheduler(bot: Bot, db: Database, settings) -> None:
    """Award birthdays once and queue Telegram delivery with durable retry."""
    log = logging.getLogger("amp.birthdays")
    while True:
        await scheduler_heartbeat(db, "birthday_scheduler")
        now = clock.now_local()
        today_nine = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now < today_nine:
            await asyncio.sleep(max(1, clock.seconds_until_local(hour=9, now_utc=clock.now_utc())))
            now = clock.now_local()
        try:
            async with job_lock(db, "birthday_rewards", ttl_seconds=3300) as acquired:
                if acquired:
                    async with db.session_factory() as session:
                        await process_expired_bans(session, clock.storage_utc())
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
            log.exception("Помилка перевірки днів народження", extra=log_extra("SCHED_BIRTHDAY_FAILED", scheduler="birthday_scheduler", exception_type=type(exc).__name__))
        await asyncio.sleep(3600)
