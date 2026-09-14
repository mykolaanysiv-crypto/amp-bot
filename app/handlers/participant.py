from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, or_, select

from ..db import Database
from ..gamification import LEVELS, get_level, progress_text
from ..keyboards import (compact_button_text, entity_button_text, events_keyboard, rewards_keyboard, tasks_keyboard,
                         main_menu, join_hub_keyboard, profile_hub_keyboard, more_hub_keyboard)
from ..media import telegram_photo_input, save_telegram_photo
from ..models import (
    ActivityApplication,
    ActivityType,
    Badge,
    Event,
    Idea,
    Opportunity,
    OpportunityInterest,
    OpportunityMatch,
    Quest,
    QuestParticipation,
    RequestCase,
    RequestMessage,
    Reward,
    RewardClaim,
    User,
    UserBadge,
    UserStatus,
    VolunteerTask, VolunteerTaskParticipation,
    XPTransaction,
)
from ..profile_data import participant_first_name
from ..services import current_season, get_user_by_tg, log_audit, season_xp, xp_total
from ..engagement import active_month_streak, goals_for_user, process_expired_content
from ..leagues import (
    MAX_FREEZE_DAYS_PER_QUARTER, create_streak_freeze, league_for_xp, league_leaderboard_rows,
    refresh_user_streak, restore_super_streak, season_leaderboard_rows, streak_freeze_summary,
)
from ..ui_labels import activity_category_label, activity_status_label, idea_status_label, label, request_status_label
from ..states import ActivityApplicationState, IdeaState, RequestState, StreakFreezeState
from ..opportunity_matching import OPPORTUNITY_INTERESTS, refresh_matches_for_user, set_user_interests, user_interests
from ..runtime_config import get_runtime_int

router = Router(name="participant")


async def _active_user(message_or_cb, db: Database):
    tg_id = message_or_cb.from_user.id
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
        return user




@router.message(F.text.in_({"🏠 Головна", "🏠 Огляд"}))
async def overview(message: Message, db: Database) -> None:
    """Participant home: a concise, useful snapshot of what matters today."""
    now = datetime.now()
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        xp = await xp_total(session, user.id)
        sxp = await season_xp(session, user.id)
        season = await current_season(session)
        streak_row, _ = await refresh_user_streak(session, user)
        league = league_for_xp(sxp)
        level_name, next_threshold = get_level(xp)
        next_event = await session.scalar(
            select(Event).where(Event.status == "open", Event.starts_at >= now).order_by(Event.starts_at.asc()).limit(1)
        )
        next_quest = await session.scalar(
            select(Quest)
            .join(QuestParticipation, QuestParticipation.quest_id == Quest.id)
            .where(
                QuestParticipation.user_id == user.id,
                QuestParticipation.status.in_(["joined", "returned", "completed"]),
                Quest.status.in_(["open", "active", "postponed"]),
                Quest.ends_at.is_not(None),
                Quest.ends_at >= now,
            )
            .order_by(Quest.ends_at.asc()).limit(1)
        )
        case_updates = int(await session.scalar(
            select(func.count(RequestCase.id)).where(RequestCase.user_id == user.id, RequestCase.status == "need_info")
        ) or 0)
        new_matches = int(await session.scalar(
            select(func.count(OpportunityMatch.id)).where(
                OpportunityMatch.user_id == user.id,
                OpportunityMatch.status.in_(["matched", "notified"]),
                OpportunityMatch.matched_at >= now - timedelta(days=7),
            )
        ) or 0)
        await session.commit()

    first_name = participant_first_name(user)
    if next_threshold is None:
        xp_line = f"⚡ <b>{xp} XP</b> · {level_name}"
        next_line = "🏆 Максимальний рівень уже досягнуто"
    else:
        xp_line = f"⚡ <b>{xp} / {next_threshold} XP</b>"
        next_line = f"До наступного рівня: <b>{max(0, next_threshold - xp)} XP</b>"
    if next_threshold:
        current_threshold = max((threshold for threshold, _ in LEVELS if threshold <= xp), default=0)
        span = max(1, next_threshold - current_threshold)
        pct = max(0, min(100, int(((xp - current_threshold) / span) * 100)))
        filled = max(0, min(10, round(pct / 10)))
        progress_bar = "█" * filled + "░" * (10 - filled)
    else:
        pct = 100
        progress_bar = "█" * 10
    lines = [
        f"👋 <b>Привіт, {escape(first_name)}!</b>",
        f"🪪 <code>АМП-{user.id:04d}</code> · <b>{escape(label(user.role))}</b>",
        "",
        "📊 <b>Твій прогрес</b>",
        xp_line,
        f"<code>{progress_bar}</code> {pct}%",
        next_line,
        f"🎒 Для винагород: <b>{int(user.wallet_xp or 0)} XP</b>",
        f"🏆 {league.icon} {league.title} · сезон{f' «{escape(season.name)}»' if season else ''}: <b>{sxp} XP</b>",
        f"🔥 Серія: <b>{int(streak_row.weekly_streak or 0)} тиж.</b> · ⏱ Волонтерство: <b>{float(user.volunteer_hours or 0):g} год.</b>",
        "",
        "📌 <b>Що важливо зараз</b>",
    ]
    if next_event:
        when = next_event.starts_at.strftime("%d.%m о %H:%M")
        lines.append(f"📅 Найближче: <b>{escape(next_event.title)}</b> — {when}")
    else:
        lines.append("📅 Найближчих відкритих подій поки немає")
    if next_quest and next_quest.ends_at:
        delta = next_quest.ends_at - now
        days = max(0, delta.days)
        if days == 0:
            q_when = "сьогодні"
        elif days == 1:
            q_when = "через 1 день"
        else:
            q_when = f"через {days} дн."
        lines.append(f"🎯 Квест «{escape(next_quest.title)}» завершується {q_when}")
    if case_updates:
        lines.append(f"🆘 У зверненнях очікує твоєї відповіді: <b>{case_updates}</b>")
    if new_matches:
        lines.append(f"🌍 Нових персональних можливостей: <b>{new_matches}</b>")
    if not case_updates:
        lines.append("🆘 У зверненнях немає нових дій")
    if not new_matches:
        lines.append("🌍 Нових персональних можливостей за 7 днів немає")
    lines.append("\n⚡ <b>Швидкі дії</b>")
    lines.append("🤝 Запросити друга · 🆘 Звернення — прямо в головному меню нижче.")
    lines.append("Обери, що хочеш зробити 👇")
    await message.answer("\n".join(lines), reply_markup=main_menu(user.role))


@router.message(F.text == "🚀 Долучитися")
async def join_hub(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
    if not user or user.status != UserStatus.ACTIVE.value:
        await message.answer("Профіль ще не активований. Натисніть /start")
        return
    await message.answer("🚀 <b>Долучитися</b>\nОбери, до чого хочеш долучитися:", reply_markup=join_hub_keyboard())


@router.message(F.text == "☰ Ще")
async def more_hub(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
    if not user or user.status != UserStatus.ACTIVE.value:
        await message.answer("Профіль ще не активований. Натисніть /start")
        return
    await message.answer("☰ <b>Ще</b>\nДодаткові можливості та допомога:", reply_markup=more_hub_keyboard())


async def _send_streak_overview(target, db: Database, tg_id: int) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await target.answer("Профіль ще не активований. Натисніть /start")
            return
        row, _ = await refresh_user_streak(session, user)
        freeze = (await streak_freeze_summary(session, [user.id])).get(user.id, {})
        freeze_limit = await get_runtime_int(session, "streak.freeze_limit_quarter")
        total_miss_limit = await get_runtime_int(session, "streak.super_total_misses")
        consecutive_miss_limit = await get_runtime_int(session, "streak.super_consecutive_misses")
        await session.commit()
    active_until = freeze.get("active_until")
    remaining = int(freeze.get("remaining", freeze_limit))
    freeze_text = (
        f"🧊 Заморожена до <b>{active_until.strftime('%d.%m.%Y %H:%M')}</b>"
        if active_until else "🧊 Зараз серія не заморожена"
    )
    b = InlineKeyboardBuilder()
    if remaining > 0:
        b.button(text=f"🧊 Заморозити серію · до {remaining} дн.", callback_data="streak:freeze")
    b.button(text="↻ Оновити", callback_data="streak:refresh")
    b.adjust(1)
    await target.answer(
        "🔥 <b>Серії участі</b>\n\n"
        f"📆 Тижнева серія: <b>{int(row.weekly_streak or 0)} тиж.</b>\n"
        f"🏅 Рекорд тижнів: <b>{int(row.weekly_best or 0)}</b>\n\n"
        f"🔥 Суперсерія подій: <b>{int(row.event_streak or 0)} подій</b>\n"
        f"🏆 Рекорд подій: <b>{int(row.event_best or 0)}</b>\n"
        f"⏭ Пропуски: <b>{int(row.event_total_misses or 0)}/{total_miss_limit}</b> · поспіль <b>{int(row.event_consecutive_misses or 0)}/{consecutive_miss_limit}</b>\n\n"
        f"{freeze_text}\n"
        f"📦 Цього кварталу використано: <b>{int(freeze.get('used', 0))}/{freeze_limit} дн.</b>\n"
        f"✅ Доступно ще: <b>{remaining} дн.</b>\n\n"
        "Під час заморозки пропущені події та тижні не обривають серію.",
        reply_markup=b.as_markup(),
    )


@router.message(F.text == "🔥 Серії участі")
async def streaks_menu(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _send_streak_overview(message, db, message.from_user.id)


@router.callback_query(F.data == "streak:refresh")
async def streaks_refresh(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _send_streak_overview(call.message, db, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "streak:freeze")
async def streak_freeze_start(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await call.answer("Профіль не активований", show_alert=True)
            return
        freeze = (await streak_freeze_summary(session, [user.id])).get(user.id, {})
        freeze_limit = await get_runtime_int(session, "streak.freeze_limit_quarter")
        remaining = int(freeze.get("remaining", freeze_limit))
    if remaining <= 0:
        await call.answer(f"Ліміт {freeze_limit} днів у цьому кварталі вже використано", show_alert=True)
        return
    await state.set_state(StreakFreezeState.days)
    await state.update_data(streak_freeze_remaining=remaining)
    await call.message.answer(
        f"🧊 <b>Заморозка серії</b>\n\nВведіть кількість днів від <b>1</b> до <b>{remaining}</b>.\n"
        f"Ліміт — {freeze_limit} днів сумарно на календарний квартал."
    )
    await call.answer()


@router.message(StreakFreezeState.days)
async def streak_freeze_days(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введіть кількість днів цілим числом, наприклад: <b>3</b>.")
        return
    days = int(raw)
    data = await state.get_data()
    remaining = int(data.get("streak_freeze_remaining") or 0)
    if days < 1 or days > remaining:
        await message.answer(f"Можна обрати від 1 до {remaining} дн.")
        return
    try:
        async with db.session_factory() as session:
            user = await get_user_by_tg(session, message.from_user.id)
            if not user or user.status != UserStatus.ACTIVE.value:
                await state.clear()
                return
            row = await create_streak_freeze(
                session, user.id, days,
                created_by_label=f"Telegram · {user.full_name}",
                note="Самостійна заморозка учасником",
            )
            await log_audit(
                session, "participant_streak_freeze", actor=user,
                entity_type="user", entity_id=user.id,
                details=f"Самостійна заморозка на {days} дн. до {row.ends_at.strftime('%d.%m.%Y %H:%M')}",
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    await state.clear()
    await message.answer(
        f"✅ <b>Готово!</b> Ваша серія заморожена на <b>{days} дн.</b>\n"
        f"До: <b>{row.ends_at.strftime('%d.%m.%Y %H:%M')}</b>.\n\n"
        "У цей період пропуски не обриватимуть серію."
    )


@router.message(F.text == "👤 Мій профіль")
async def profile(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        xp = await xp_total(session, user.id)
        sxp = await season_xp(session, user.id)
        season = await current_season(session)
        tx_count = await session.scalar(select(func.count(XPTransaction.id)).where(XPTransaction.user_id == user.id))
        badges = await session.scalar(select(func.count(UserBadge.id)).where(UserBadge.user_id == user.id))
        streak = await active_month_streak(session, user.id)
        streak_row, _ = await refresh_user_streak(session, user)
        await session.commit()
        league = league_for_xp(sxp)
        b = profile_hub_keyboard()
        await message.answer(
            f"👤 <b>{user.full_name}</b>\n"
            f"ID АМП: <code>АМП-{user.id:04d}</code>\n\n"
            f"{progress_text(xp)}\n"
            f"📈 XP сезону{f' «{season.name}»' if season else ''}: <b>{sxp}</b>\n"
            f"🏆 Ліга: <b>{league.icon} {league.title}</b>\n"
            f"💳 Доступно для обміну: <b>{user.wallet_xp} XP</b>\n"
            f"⏱ Волонтерських годин: <b>{user.volunteer_hours:g}</b>\n"
            f"🏅 Бейджів: <b>{badges or 0}</b>\n"
            f"🧾 XP-операцій: <b>{tx_count or 0}</b>\n"
            f"🔥 Серія активних місяців: <b>{streak}</b>\n"
            f"📆 Тижнева серія: <b>{streak_row.weekly_streak}</b> тиж.\n"
            f"🔥 Суперсерія подій: <b>{streak_row.event_streak}</b> відвідувань\n\n"
            f"Роль: <b>{label(user.role)}</b>",
            reply_markup=b,
        )


AMBASSADOR_BADGE_ROLES = {"ambassador", "coordinator", "admin", "superadmin"}


async def _send_badge_list(target, db: Database, tg_id: int, badge_type: str) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
        if not user or user.status != UserStatus.ACTIVE.value:
            return
        rows = (await session.execute(
            select(Badge).join(UserBadge, UserBadge.badge_id == Badge.id)
            .where(UserBadge.user_id == user.id, Badge.badge_type == badge_type)
            .order_by(UserBadge.awarded_at.desc())
        )).scalars().all()
        title = "🚀 <b>Бейджі АМПасадора</b>" if badge_type == "ambassador" else "🏅 <b>Загальні бейджі</b>"
        if not rows:
            b=InlineKeyboardBuilder(); b.button(text="⬅️ Назад",callback_data="badge_menu_back")
            await target.answer(f"{title}\n\nПоки що в цьому розділі бейджів немає.", reply_markup=b.as_markup())
            return
        lines=[title,""]
        for badge in rows:
            lines.append(f"{badge.icon} <b>{badge.name}</b> — {badge.description}")
        b=InlineKeyboardBuilder(); b.button(text="⬅️ Назад",callback_data="badge_menu_back")
        await target.answer("\n".join(lines), reply_markup=b.as_markup())
        if badge_type == "ambassador":
            for badge in rows:
                photo=await telegram_photo_input(db, badge.image_path)
                if photo:
                    try: await target.answer_photo(photo, caption=f"{badge.icon} <b>{badge.name}</b>\n{badge.description}")
                    except Exception: pass


@router.message(F.text == "⚡ Мій XP")
async def xp_history(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        total = await xp_total(session, user.id)
        rows = list((await session.scalars(
            select(XPTransaction).where(XPTransaction.user_id == user.id).order_by(XPTransaction.created_at.desc()).limit(10)
        )).all())
    lines = ["⚡ <b>Мій XP</b>", progress_text(total), f"💳 Баланс винагород: <b>{user.wallet_xp} XP</b>"]
    if rows:
        lines.append("\n<b>Останні операції</b>")
        for row in rows:
            sign = "+" if int(row.amount or 0) >= 0 else ""
            lines.append(f"• {row.created_at.strftime('%d.%m')} · <b>{sign}{int(row.amount or 0)} XP</b> · {escape(row.reason or row.category or 'Операція')}")
    await message.answer("\n".join(lines))


@router.message(F.text == "🏅 Бейджі")
async def badges(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            return
        is_ambassador = user.role in AMBASSADOR_BADGE_ROLES
    if not is_ambassador:
        await _send_badge_list(message, db, message.from_user.id, "general")
        return
    b=InlineKeyboardBuilder()
    b.button(text="🏅 Загальні бейджі",callback_data="badge_list:general")
    b.button(text="🚀 Бейджі АМПасадора",callback_data="badge_list:ambassador")
    b.adjust(1)
    await message.answer("🏅 <b>Мої бейджі</b>\n\nОберіть розділ:",reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("badge_list:"))
async def badge_list_callback(call: CallbackQuery, db: Database) -> None:
    badge_type=call.data.split(":",1)[1]
    if badge_type not in {"general","ambassador"}:
        await call.answer(); return
    await _send_badge_list(call.message,db,call.from_user.id,badge_type)
    await call.answer()


@router.callback_query(F.data == "badge_menu_back")
async def badge_menu_back(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        if user.role in AMBASSADOR_BADGE_ROLES:
            b=InlineKeyboardBuilder(); b.button(text="🏅 Загальні бейджі",callback_data="badge_list:general"); b.button(text="🚀 Бейджі АМПасадора",callback_data="badge_list:ambassador"); b.adjust(1)
            await call.message.answer("🏅 <b>Мої бейджі</b>\n\nОберіть розділ:",reply_markup=b.as_markup())
        else:
            await _send_badge_list(call.message,db,call.from_user.id,"general")
    await call.answer()


@router.message(F.text == "🎁 Винагороди")
async def rewards(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            return
        rows = (await session.scalars(select(Reward).where(Reward.active == True).order_by(Reward.min_xp))).all()  # noqa: E712
        if not rows:
            await message.answer("🎁 Винагороди ще не додані.")
            return
        await message.answer(f"🎁 <b>Винагороди АМП XP</b>\n💳 Твій баланс: <b>{user.wallet_xp} XP</b>\nОбирай винагороду — XP списуються з гаманця, але загальний досвід і рівень залишаються.", reply_markup=rewards_keyboard(rows))


@router.callback_query(F.data.startswith("reward:"))
async def reward_detail(call: CallbackQuery, db: Database) -> None:
    reward_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        reward = await session.get(Reward, reward_id)
        if not user or not reward:
            await call.answer("Не знайдено", show_alert=True)
            return
        stock = "∞" if reward.stock is None else str(reward.stock)
        special = "\n🔥 <b>Ефект:</b> відновлює останню втрачену суперсерію подій." if getattr(reward, "reward_type", "item") == "streak_restore" else ""
        text = (
            f"🎁 <b>{reward.title}</b>\n"
            f"💳 Вартість: <b>{reward.min_xp} XP</b>\n"
            f"Твій баланс: <b>{user.wallet_xp} XP</b>\n"
            f"В наявності: <b>{stock}</b>\n\n{reward.description}{special}"
        )
        b = InlineKeyboardBuilder()
        can_claim = (reward.stock is None or reward.stock > 0) and user.wallet_xp >= reward.min_xp
        if can_claim:
            b.button(text=f"🔄 Обміняти {reward.min_xp} XP", callback_data=f"reward_claim:{reward.id}")
        else:
            b.button(text="⛔ Недоступно", callback_data="noop")
        b.button(text="⬅️ Назад", callback_data="nav:rewards")
        b.adjust(1)
        photo = await telegram_photo_input(db, reward.image_path)
        if photo:
            await call.message.answer_photo(photo, caption=text, reply_markup=b.as_markup())
        else:
            await call.message.answer(text, reply_markup=b.as_markup())
        await call.answer()


@router.callback_query(F.data == "nav:rewards")
async def nav_rewards(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await call.answer("Профіль не активований", show_alert=True); return
        rows = (await session.scalars(select(Reward).where(Reward.active == True).order_by(Reward.min_xp))).all()  # noqa: E712
        if rows:
            await call.message.answer(f"🎁 <b>Винагороди АМП XP</b>\n💳 Твій баланс: <b>{user.wallet_xp} XP</b>", reply_markup=rewards_keyboard(rows))
        else:
            await call.message.answer("🎁 Винагороди ще не додані.")
    await call.answer()


@router.callback_query(F.data.startswith("reward_claim:"))
async def reward_claim(call: CallbackQuery, db: Database) -> None:
    reward_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        reward = await session.get(Reward, reward_id)
        if not user or not reward or not reward.active:
            await call.answer("Не знайдено", show_alert=True)
            return
        if reward.stock is not None and reward.stock <= 0:
            await call.answer("Винагорода закінчилась", show_alert=True)
            return
        if user.wallet_xp < reward.min_xp:
            await call.answer(f"Потрібно ще {reward.min_xp - user.wallet_xp} XP у гаманці", show_alert=True)
            return
        if getattr(reward, "reward_type", "item") == "streak_restore":
            await refresh_user_streak(session, user)
            restored, streak_row = await restore_super_streak(session, user)
            if not restored:
                await call.answer("Немає втраченої суперсерії, яку можна відновити", show_alert=True)
                return
            user.wallet_xp -= reward.min_xp
            if reward.stock is not None:
                reward.stock -= 1
            await log_audit(
                session, "telegram_streak_restore_reward", actor=user, entity_type="reward", entity_id=reward.id,
                details=f"Відновлено суперсерію; списано {reward.min_xp} XP; серія={streak_row.event_streak}",
            )
            await session.commit()
            await call.message.answer(
                f"🔥 <b>Суперсерію відновлено!</b>\n"
                f"Поточна серія: <b>{streak_row.event_streak}</b> відвідувань.\n"
                f"Списано: <b>{reward.min_xp} XP</b>. Баланс: <b>{user.wallet_xp} XP</b>."
            )
            await call.answer("Серію відновлено")
            return
        existing = await session.scalar(select(RewardClaim).where(RewardClaim.reward_id == reward.id, RewardClaim.user_id == user.id))
        if existing and existing.status == "requested":
            await call.answer("Заявка на цю винагороду вже очікує підтвердження", show_alert=True)
            return
        if existing and existing.status == "fulfilled" and getattr(reward, "reward_type", "item") != "service":
            await call.answer("Ти вже отримав/ла цю винагороду", show_alert=True)
            return
        user.wallet_xp -= reward.min_xp
        if reward.stock is not None:
            reward.stock -= 1
        if existing:
            existing.status = "requested"
            existing.xp_spent = reward.min_xp
            existing.requested_at = datetime.utcnow()
            existing.fulfilled_at = None
        else:
            session.add(RewardClaim(reward_id=reward.id, user_id=user.id, xp_spent=reward.min_xp))
        await session.commit()
        await call.message.answer(
            f"✅ Обмін підтверджено. Списано <b>{reward.min_xp} XP</b>.\n"
            f"💳 Залишок: <b>{user.wallet_xp} XP</b>.\n"
            "Заявку передано адміністратору."
        )
        await call.answer("Заявку створено")


@router.message(F.text.in_({"💡 Нова ідея", "💡 Запропонувати ідею"}))
async def idea_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(IdeaState.title)
    await message.answer(
        "💡 <b>Нова ідея для АМП</b>\n\n"
        "Ми поставимо кілька коротких питань. У вебпанелі відповіді будуть показані окремими полями, щоб команді було легко розглянути ідею.\n\n"
        "1/6. Напиши коротку <b>назву ідеї</b>."
    )


@router.message(IdeaState.title)
async def idea_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 3:
        await message.answer("Назва надто коротка.")
        return
    await state.update_data(title=title)
    await state.set_state(IdeaState.category)
    b = InlineKeyboardBuilder()
    for text, value in [
        ("🎉 Подія / активність", "event_idea"), ("🏠 Розвиток простору", "space"),
        ("🎓 Освіта", "education"), ("📣 Комунікації / медіа", "media"),
        ("🤝 Волонтерство", "volunteering"), ("🌐 Партнерства", "partnership"),
        ("💭 Інше", "other"),
    ]:
        b.button(text=text, callback_data=f"idea_cat:{value}")
    b.adjust(2)
    await message.answer("2/6. Обери <b>напрям ідеї</b>.", reply_markup=b.as_markup())


@router.callback_query(IdeaState.category, F.data.startswith("idea_cat:"))
async def idea_category(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 1)[1]
    labels = {
        "event_idea": "🎉 Подія / активність", "space": "🏠 Розвиток простору",
        "education": "🎓 Освіта", "media": "📣 Комунікації / медіа",
        "volunteering": "🤝 Волонтерство", "partnership": "🌐 Партнерства", "other": "💭 Інше",
    }
    await state.update_data(category=value)
    # Keep the selected choice visibly framed in the inline-button area before
    # moving to the next question. Telegram does not support CSS button states,
    # so a checked, non-action button is the clearest persistent selection cue.
    selected = InlineKeyboardBuilder()
    selected.button(text=f"✅ {labels.get(value, value)}", callback_data="noop")
    try:
        await call.message.edit_reply_markup(reply_markup=selected.as_markup())
    except Exception:
        pass
    await state.set_state(IdeaState.problem)
    await call.message.answer(f"✅ Обраний напрям: <b>{labels.get(value, value)}</b>\n\n3/6. Яку <b>проблему або потребу</b> має вирішити ця ідея?")
    await call.answer("Вибір збережено")


@router.message(IdeaState.problem)
async def idea_problem(message: Message, state: FSMContext) -> None:
    await state.update_data(problem=(message.text or "").strip())
    await state.set_state(IdeaState.description)
    await message.answer("4/6. Опиши <b>що саме пропонуєш зробити</b>.")


@router.message(IdeaState.description)
async def idea_description_step(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(IdeaState.audience)
    await message.answer("5/6. Для <b>кого</b> ця ідея? Вкажи цільову аудиторію.")


@router.message(IdeaState.audience)
async def idea_audience(message: Message, state: FSMContext) -> None:
    await state.update_data(audience=(message.text or "").strip())
    await state.set_state(IdeaState.expected_result)
    await message.answer("6/6. Який <b>результат</b> хочеш отримати після реалізації?")


@router.message(IdeaState.expected_result)
async def idea_result(message: Message, state: FSMContext) -> None:
    await state.update_data(expected_result=(message.text or "").strip())
    await state.set_state(IdeaState.resources)
    await message.answer("Додатково: які <b>ресурси / допомога</b> можуть знадобитися? Якщо не знаєш — напиши «не знаю».")


@router.message(IdeaState.resources)
async def idea_resources(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        session.add(Idea(
            user_id=user.id,
            title=data["title"],
            category=data.get("category", "other"),
            problem=data.get("problem", ""),
            description=data.get("description", ""),
            audience=data.get("audience", ""),
            expected_result=data.get("expected_result", ""),
            resources=(message.text or "").strip(),
            status="new",
            updated_at=datetime.utcnow(),
        ))
        await session.commit()
    await state.clear()
    await message.answer("✅ Ідею збережено. У вебпанелі команда побачить усі відповіді окремими блоками та зможе змінювати її статус у будь-який момент.")


@router.message(F.text == "🆘 Звернення")
async def request_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="➕ Нове звернення", callback_data="request:new")
    b.button(text="📋 Мої звернення", callback_data="request:list")
    b.adjust(1)
    await message.answer(
        "🆘 <b>Звернення до команди АМП</b>\n\n"
        "Тут можна повідомити про проблемне питання, інцидент, безпеку, скаргу, технічну проблему або подати пропозицію.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "request:new")
async def request_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RequestState.category)
    b = InlineKeyboardBuilder()
    for text, value in [
        ("⚠️ Проблемне питання", "problem"), ("🚨 Інцидент", "incident"),
        ("🛡 Безпека", "safety"), ("🗣 Скарга", "complaint"),
        ("💬 Пропозиція", "proposal"), ("🧰 Технічне питання", "technical"),
        ("📌 Інше", "other"),
    ]:
        b.button(text=text, callback_data=f"request_cat:{value}")
    b.adjust(2)
    await call.message.answer("Оберіть тип звернення:", reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(RequestState.category, F.data.startswith("request_cat:"))
async def request_category(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(category=call.data.split(":", 1)[1])
    await state.set_state(RequestState.title)
    await call.message.answer("Коротко напишіть <b>тему звернення</b>.")
    await call.answer()


@router.message(RequestState.title)
async def request_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 3:
        await message.answer("Тема надто коротка.")
        return
    await state.update_data(title=title)
    await state.set_state(RequestState.description)
    await message.answer("Опишіть ситуацію детальніше: що сталося / у чому проблема / чого очікуєте від команди АМП?")


@router.message(RequestState.description)
async def request_description(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    if len(description) < 5:
        await message.answer("Опишіть ситуацію трохи детальніше.")
        return
    await state.update_data(description=description)
    await state.set_state(RequestState.has_photo)
    b = InlineKeyboardBuilder()
    b.button(text="📷 Так, додати фото", callback_data="request_photo:yes")
    b.button(text="➡️ Без фото", callback_data="request_photo:no")
    b.adjust(1)
    await message.answer("📷 <b>Чи маєте ви фото, яке допоможе зрозуміти звернення?</b>", reply_markup=b.as_markup())


async def _create_request_case(message_or_call, state: FSMContext, db: Database, image_path: str | None = None) -> str | None:
    data = await state.get_data()
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message_or_call.from_user.id)
        if not user:
            await state.clear()
            return None
        category = data.get("category", "problem")
        priority = "high" if category in {"incident", "safety"} else "normal"
        case = RequestCase(
            user_id=user.id,
            category=category,
            title=data["title"],
            description=data.get("description", ""),
            priority=priority,
            status="new",
            image_path=image_path,
            updated_at=datetime.utcnow(),
        )
        session.add(case)
        await session.flush()
        case.case_number = f"AMP-{case.created_at.year}-{case.id:04d}"
        session.add(RequestMessage(
            case_id=case.id,
            sender_type="participant",
            sender_user_id=user.id,
            body=case.description,
            image_path=image_path,
            created_at=case.created_at,
        ))
        await session.commit()
        case_number = case.case_number
    await state.clear()
    return case_number


@router.callback_query(RequestState.has_photo, F.data == "request_photo:no")
async def request_without_photo(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    case_number = await _create_request_case(call, state, db)
    if case_number:
        await call.message.answer(f"✅ Звернення <b>{case_number}</b> зареєстровано. Статус, дедлайн відповіді та переписку можна переглядати в розділі «Мої звернення».")
    await call.answer()


@router.callback_query(RequestState.has_photo, F.data == "request_photo:yes")
async def request_with_photo_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RequestState.photo)
    await call.message.answer("📷 Надішліть <b>одне фото</b> у цей чат. Максимальний розмір — 20 МБ.\n\nЯкщо передумали, введіть /cancel і створіть звернення заново.")
    await call.answer()


@router.message(RequestState.photo, F.photo)
async def request_photo_received(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    try:
        image_path = await save_telegram_photo(bot, message.photo[-1].file_id, "requests", db, max_mb=20)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    case_number = await _create_request_case(message, state, db, image_path=image_path)
    if case_number:
        await message.answer(f"✅ Звернення <b>{case_number}</b> зареєстровано разом із фото. Статус і переписку можна переглядати в розділі «Мої звернення».")


@router.message(RequestState.photo)
async def request_photo_wrong_type(message: Message) -> None:
    await message.answer("Надішліть, будь ласка, саме фото як зображення.")


@router.callback_query(F.data == "request:list")
async def request_list(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer()
            return
        rows = (await session.scalars(
            select(RequestCase).where(RequestCase.user_id == user.id).order_by(RequestCase.created_at.desc()).limit(10)
        )).all()
        if not rows:
            await call.message.answer("У вас ще немає звернень.")
        else:
            b = InlineKeyboardBuilder()
            for c in rows:
                number = c.case_number or f"AMP-{c.created_at.year}-{c.id:04d}"
                b.button(text=compact_button_text(f"🆘 {number} · {request_status_label(c.status)}"), callback_data=f"request:view:{c.id}")
            b.adjust(1)
            await call.message.answer("🆘 <b>Мої звернення</b>\nОберіть кейс, щоб переглянути статус, дедлайн і переписку.", reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("request:view:"))
async def request_view(call: CallbackQuery, db: Database) -> None:
    case_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        case = await session.get(RequestCase, case_id)
        if not user or not case or case.user_id != user.id:
            await call.answer("Звернення не знайдено", show_alert=True)
            return
        messages = list((await session.scalars(
            select(RequestMessage).where(RequestMessage.case_id == case.id).order_by(RequestMessage.created_at.desc()).limit(6)
        )).all())[::-1]
        number = case.case_number or f"AMP-{case.created_at.year}-{case.id:04d}"
        deadline = case.response_deadline.strftime("%d.%m.%Y %H:%M") if case.response_deadline else "не встановлено"
        parts = [
            f"🆘 <b>{number}</b>",
            f"<b>{escape(case.title)}</b>",
            f"📌 {request_status_label(case.status)} · {label(case.priority)}",
            f"⏳ Дедлайн відповіді: <b>{deadline}</b>",
        ]
        if messages:
            parts.append("\n💬 <b>Останні повідомлення</b>")
            for item in messages:
                who = "Ви" if item.sender_type == "participant" else ("Команда АМП" if item.sender_type == "admin" else "Система")
                body = escape((item.body or "📎 Вкладення").strip())
                attachment = "\n📎 Є вкладення" if item.image_path else ""
                parts.append(f"\n<b>{who}</b> · {item.created_at.strftime('%d.%m %H:%M')}\n{body}{attachment}")
        b = InlineKeyboardBuilder()
        if case.status != "case_closed":
            b.button(text="✍️ Написати", callback_data=f"request:reply:{case.id}")
        b.button(text="↩️ До звернень", callback_data="request:list")
        b.adjust(1)
        await call.message.answer("\n".join(parts), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("request:reply:"))
async def request_reply_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    case_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        case = await session.get(RequestCase, case_id)
        if not user or not case or case.user_id != user.id or case.status == "case_closed":
            await call.answer("Кейс недоступний", show_alert=True)
            return
    await state.set_state(RequestState.reply)
    await state.update_data(reply_case_id=case_id)
    await call.message.answer("✍️ Надішліть <b>текст або фото</b> у переписку цього звернення. Для виходу — /cancel.")
    await call.answer()


@router.message(RequestState.reply, F.photo)
async def request_reply_photo(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    data = await state.get_data()
    case_id = int(data.get("reply_case_id") or 0)
    try:
        image_path = await save_telegram_photo(bot, message.photo[-1].file_id, "requests", db, max_mb=20)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        case = await session.get(RequestCase, case_id)
        if not user or not case or case.user_id != user.id:
            await state.clear(); return
        body = (message.caption or "Фото від учасника").strip()
        session.add(RequestMessage(case_id=case.id, sender_type="participant", sender_user_id=user.id, body=body, image_path=image_path))
        case.updated_at = datetime.utcnow()
        await session.commit()
    await state.clear()
    await message.answer("✅ Фото додано до переписки звернення.")


@router.message(RequestState.reply)
async def request_reply_text(message: Message, state: FSMContext, db: Database) -> None:
    body = (message.text or "").strip()
    if len(body) < 1:
        await message.answer("Напишіть повідомлення або надішліть фото.")
        return
    data = await state.get_data()
    case_id = int(data.get("reply_case_id") or 0)
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        case = await session.get(RequestCase, case_id)
        if not user or not case or case.user_id != user.id:
            await state.clear(); return
        session.add(RequestMessage(case_id=case.id, sender_type="participant", sender_user_id=user.id, body=body))
        case.updated_at = datetime.utcnow()
        await session.commit()
    await state.clear()
    await message.answer("✅ Повідомлення додано до звернення.")


@router.message(F.text.in_({"📰 Можливості", "🌍 Можливості"}))
async def opportunities(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        await refresh_matches_for_user(session, user)
        await session.flush()
        matched_ids = dict((await session.execute(
            select(OpportunityMatch.opportunity_id, OpportunityMatch.score).where(OpportunityMatch.user_id == user.id, OpportunityMatch.status.in_(["matched", "notified"]))
        )).all())
        rows = list((await session.scalars(
            select(Opportunity).where(
                Opportunity.active == True,  # noqa: E712
                (Opportunity.deadline.is_(None)) | (Opportunity.deadline >= datetime.utcnow()),
            ).order_by(Opportunity.deadline.asc().nullslast(), Opportunity.id.desc())
        )).all())
        rows.sort(key=lambda o: (0 if o.id in matched_ids else 1, -int(matched_ids.get(o.id, 0)), o.deadline or datetime.max))
        await session.commit()
        if not rows:
            await message.answer("🌍 Зараз немає актуальних можливостей для молоді.")
            return
        b = InlineKeyboardBuilder()
        interests = user_interests(user)
        lines = [
            "🌍 <b>Можливості для молоді</b>",
            "Персональні збіги показуються першими.",
            f"🎯 Інтереси: <b>{', '.join(interests) if interests else 'ще не обрано'}</b>",
            "",
            "<b>Оберіть можливість:</b>",
        ]
        for idx, o in enumerate(rows[:20], start=1):
            deadline = o.deadline.strftime("%d.%m.%Y") if o.deadline else "без дедлайну"
            score = matched_ids.get(o.id)
            prefix = f"✨ {score}% match · " if score else ""
            lines.append(f"\n<b>{idx}. {escape(o.title)}</b>\n{prefix}📆 {deadline} • {escape(o.kind or 'можливість')}")
            label_text = f"✨ {o.title}" if score else f"🌍 {o.title}"
            b.button(text=entity_button_text(label_text), callback_data=f"opp:{o.id}")
        b.button(text="⚙️ Мої інтереси", callback_data="opp_prefs")
        b.adjust(1)
        await message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data == "opp_prefs")
async def opportunity_preferences(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await call.answer("Профіль неактивний", show_alert=True); return
        selected = set(user_interests(user))
        b = InlineKeyboardBuilder()
        for idx, item in enumerate(OPPORTUNITY_INTERESTS):
            mark = "✅" if item in selected else "▫️"
            b.button(text=f"{mark} {item}", callback_data=f"opp_pref_toggle:{idx}")
        b.button(text="💾 Готово", callback_data="opp_pref_done")
        b.adjust(2, 2, 2, 2, 1, 1)
        await call.message.answer(
            "⚙️ <b>Інтереси для Smart Opportunities</b>\n\n"
            "Обери теми, які тобі цікаві. Matching використовує лише вік, ці інтереси, населений пункт, формат і дедлайн. "
            "Категорії вразливості не використовуються.",
            reply_markup=b.as_markup(),
        )
    await call.answer()


@router.callback_query(F.data.startswith("opp_pref_toggle:"))
async def opportunity_preference_toggle(call: CallbackQuery, db: Database) -> None:
    try: idx = int(call.data.rsplit(":", 1)[1]); item = OPPORTUNITY_INTERESTS[idx]
    except Exception:
        await call.answer("Невірний вибір", show_alert=True); return
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user: await call.answer(); return
        selected = set(user_interests(user))
        if item in selected: selected.remove(item)
        else: selected.add(item)
        set_user_interests(user, selected)
        await refresh_matches_for_user(session, user)
        await session.commit()
        b = InlineKeyboardBuilder()
        for i, option in enumerate(OPPORTUNITY_INTERESTS):
            b.button(text=f"{'✅' if option in selected else '▫️'} {option}", callback_data=f"opp_pref_toggle:{i}")
        b.button(text="💾 Готово", callback_data="opp_pref_done")
        b.adjust(2, 2, 2, 2, 1, 1)
        try:
            await call.message.edit_reply_markup(reply_markup=b.as_markup())
        except Exception:
            pass
    await call.answer("Збережено")


@router.callback_query(F.data == "opp_pref_done")
async def opportunity_preferences_done(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        selected = user_interests(user) if user else []
    await call.message.answer(f"✅ Інтереси збережено: <b>{', '.join(selected) if selected else 'не обрано'}</b>\n\nНові персональні можливості надходитимуть автоматично.")
    await call.answer()


@router.callback_query(F.data.startswith("opp:"))
async def opportunity_detail(call: CallbackQuery, db: Database) -> None:
    opportunity_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(Opportunity, opportunity_id)
        if not user or not item or not item.active or (item.deadline and item.deadline < datetime.utcnow()):
            await call.answer("Можливість уже неактуальна", show_alert=True)
            return
        interest = await session.scalar(select(OpportunityInterest).where(OpportunityInterest.opportunity_id == item.id, OpportunityInterest.user_id == user.id))
        match = await session.scalar(select(OpportunityMatch).where(OpportunityMatch.opportunity_id == item.id, OpportunityMatch.user_id == user.id))
        age_text = ""
        if item.age_min is not None or item.age_max is not None:
            age_text = f"\n🎂 Вік: {item.age_min if item.age_min is not None else '—'}–{item.age_max if item.age_max is not None else '—'}"
        deadline = item.deadline.strftime("%d.%m.%Y %H:%M") if item.deadline else "без дедлайну"
        link = f"\n🔗 {item.url}" if item.url else ""
        match_text = f"\n✨ Персональний збіг: <b>{match.score}%</b>" if match else ""
        place_text = f"\n📍 Для: {escape(item.target_settlements)}" if item.target_settlements else ""
        text = (
            f"🌍 <b>{item.title}</b>\n"
            f"🏷 {item.kind} • {item.direction}\n"
            f"💻 Формат: {item.format}{age_text}{place_text}{match_text}\n"
            f"📆 Дедлайн: {deadline}\n\n{item.description}{link}"
        )
        b = InlineKeyboardBuilder()
        if interest and interest.status == "interested":
            b.button(text="💔 Не цікаво", callback_data=f"opp_uninterest:{item.id}")
        else:
            b.button(text="💙 Мені цікаво", callback_data=f"opp_interest:{item.id}")
        b.button(text="⬅️ Назад", callback_data="nav:opportunities")
        b.adjust(1)
        await call.message.answer(text, reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("opp_interest:"))
async def opportunity_interest(call: CallbackQuery, db: Database) -> None:
    opportunity_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(Opportunity, opportunity_id)
        if not user or not item or not item.active:
            await call.answer("Можливість недоступна", show_alert=True); return
        row = await session.scalar(select(OpportunityInterest).where(OpportunityInterest.opportunity_id == item.id, OpportunityInterest.user_id == user.id))
        if row:
            row.status = "interested"; row.updated_at = datetime.utcnow()
        else:
            session.add(OpportunityInterest(opportunity_id=item.id, user_id=user.id, status="interested"))
        await session.commit()
    await call.message.answer("💙 Позначено «Мені цікаво». Команда АМП бачить лише факт інтересу до можливості.")
    await call.answer()


@router.callback_query(F.data.startswith("opp_uninterest:"))
async def opportunity_uninterest(call: CallbackQuery, db: Database) -> None:
    opportunity_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer(); return
        row = await session.scalar(select(OpportunityInterest).where(OpportunityInterest.opportunity_id == opportunity_id, OpportunityInterest.user_id == user.id))
        if row:
            row.status = "not_interested"; row.updated_at = datetime.utcnow(); await session.commit()
    await call.message.answer("Готово. Позначку інтересу прибрано.")
    await call.answer()


@router.message(F.text == "🏁 Цілі & місії")
async def participant_goals(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        streak = await active_month_streak(session, user.id)
        rows = await goals_for_user(session, user)
        if not rows:
            await message.answer(f"🏁 <b>Цілі & місії</b>\n\n🔥 Серія активних місяців: <b>{streak}</b>\n\nАктивних місій або персональних цілей зараз немає.")
            return
        await message.answer(f"🏁 <b>Цілі & місії</b>\n\n🔥 Серія активних місяців: <b>{streak}</b>\n\nПрогрес сезонних місій рахується особисто для тебе; командні цілі АМПасадорів — спільно.")
        for row in rows:
            g=row["goal"]
            scope={"season":"🌟 Сезонна місія","personal":"🎯 Персональна ціль","team":"👥 Командна ціль"}.get(g.scope,g.scope)
            parts=[
                scope,
                f"<b>{escape(g.title)}</b>",
                f"\n📌 {escape(g.task_text or g.description or 'Виконай умову місії.')}",
                f"📊 Прогрес: <b>{row['progress']:g} / {row['target']:g} {escape(row['metric_label'])}</b> • {row['percent']:g}%",
                f"🎁 Нагорода: <b>+{g.reward_xp} XP</b>" if g.reward_xp else "🎁 Без XP-нагороди",
            ]
            if g.description and g.description != g.task_text:
                parts.append(f"ℹ️ {escape(g.description)}")
            if g.ends_at:
                parts.append(f"⏳ Дедлайн: <b>{g.ends_at.strftime('%d.%m.%Y %H:%M')}</b>")
            text="\n".join(parts)
            if g.image_path:
                photo=await telegram_photo_input(db, g.image_path)
                if photo:
                    try:
                        await message.answer_photo(photo,caption=text)
                        continue
                    except Exception:
                        pass
            await message.answer(text)


# ---------- XP activity catalog ----------
@router.message(F.text == "⚡ Активності")
async def activity_catalog(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        rows = (await session.scalars(
            select(ActivityType).where(ActivityType.active == True).order_by(ActivityType.sort_order, ActivityType.title)  # noqa: E712
        )).all()
        mine = (await session.scalars(
            select(ActivityApplication).where(ActivityApplication.user_id == user.id).order_by(ActivityApplication.requested_at.desc()).limit(12)
        )).all()
        b = InlineKeyboardBuilder()
        activity_lines = []
        for idx, item in enumerate(rows, start=1):
            activity_lines.append(
                f"<b>{idx}. {escape(item.title)}</b>\n⚡ {item.xp_reward} XP • ⏱ {item.hours_reward:g} год."
            )
            b.button(text=entity_button_text(f"⚡ {item.title} · {item.xp_reward} XP"), callback_data=f"activity:{item.id}")
        if mine:
            b.button(text="📋 Мої заявки", callback_data="activity:mine")
        b.adjust(1)
        catalog = "\n\n".join(activity_lines) if activity_lines else "Активностей зараз немає."
        await message.answer(
            "⚡ <b>Активності АМП XP</b>\n\n"
            "Спочатку подайте заявку. Після погодження виконайте активність і надішліть результат — XP та години нараховуються після підтвердження.\n\n"
            "<b>Доступні активності:</b>\n\n"
            f"{catalog}",
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data == "activity:mine")
async def activity_mine(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer()
            return
        rows = (await session.execute(
            select(ActivityApplication, ActivityType)
            .join(ActivityType, ActivityType.id == ActivityApplication.activity_type_id)
            .where(ActivityApplication.user_id == user.id)
            .order_by(ActivityApplication.requested_at.desc()).limit(15)
        )).all()
        if not rows:
            await call.message.answer("📋 У вас ще немає заявок на активності.")
        else:
            b = InlineKeyboardBuilder()
            lines = ["📋 <b>Мої заявки на активності</b>"]
            for app, item in rows:
                lines.append(f"\n<b>#{app.id} • {item.title}</b>\n{activity_status_label(app.status)} • {app.xp_reward} XP • {app.hours_reward:g} год.")
                b.button(text=entity_button_text(f"📋 #{app.id} · {item.title}"), callback_data=f"activity_app:{app.id}")
            b.button(text="⬅️ Назад", callback_data="nav:activities")
            b.adjust(1)
            await call.message.answer("\n".join(lines), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.regexp(r"^activity:\d+$"))
async def activity_detail(call: CallbackQuery, db: Database) -> None:
    try:
        activity_id = int(call.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await call.answer("Не знайдено", show_alert=True)
        return
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(ActivityType, activity_id)
        if not user or not item or not item.active:
            await call.answer("Активність недоступна", show_alert=True)
            return
        active_app = await session.scalar(
            select(ActivityApplication).where(
                ActivityApplication.user_id == user.id,
                ActivityApplication.activity_type_id == item.id,
                ActivityApplication.status.in_(["activity_requested", "activity_approved", "activity_submitted"]),
            ).order_by(ActivityApplication.requested_at.desc())
        )
        b = InlineKeyboardBuilder()
        if active_app:
            b.button(text=compact_button_text(f"📋 Заявка · {activity_status_label(active_app.status)}"), callback_data=f"activity_app:{active_app.id}")
        else:
            b.button(text="🙋 Подати заявку", callback_data=f"activity_apply:{item.id}")
        b.button(text="⬅️ Назад", callback_data="nav:activities")
        b.adjust(1)
        await call.message.answer(
            f"⚡ <b>{item.title}</b>\n"
            f"🏷 Категорія: <b>{activity_category_label(item.category)}</b>\n"
            f"🎁 <b>{item.xp_reward} XP</b> • ⏱ <b>{item.hours_reward:g} год.</b>\n\n"
            f"{item.description}\n\n"
            f"<b>Що написати в заявці:</b>\n{item.instructions}",
            reply_markup=b.as_markup(),
        )
    await call.answer()


@router.callback_query(F.data.startswith("activity_apply:"))
async def activity_apply_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    activity_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(ActivityType, activity_id)
        if not user or not item or not item.active:
            await call.answer("Активність недоступна", show_alert=True)
            return
        existing = await session.scalar(select(ActivityApplication).where(
            ActivityApplication.user_id == user.id,
            ActivityApplication.activity_type_id == item.id,
            ActivityApplication.status.in_(["activity_requested", "activity_approved", "activity_submitted"]),
        ))
        if existing:
            await call.answer("У вас уже є активна заявка на цю активність", show_alert=True)
            return
    await state.set_state(ActivityApplicationState.plan_text)
    await state.update_data(activity_type_id=activity_id)
    await call.message.answer(
        "📝 <b>Опишіть план виконання</b>\n\n"
        "Напишіть коротко: що саме ви зробите, коли/де це планується та який результат очікуєте. "
        "Заявка спочатку має бути погоджена адміністратором."
    )
    await call.answer()


@router.message(ActivityApplicationState.plan_text)
async def activity_apply_finish(message: Message, state: FSMContext, db: Database) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer("Будь ласка, опишіть план трохи детальніше — щонайменше 10 символів.")
        return
    data = await state.get_data()
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        item = await session.get(ActivityType, int(data["activity_type_id"]))
        if not user or not item:
            await state.clear()
            return
        app = ActivityApplication(
            activity_type_id=item.id, user_id=user.id, status="activity_requested",
            plan_text=text, xp_reward=item.xp_reward, hours_reward=item.hours_reward,
        )
        session.add(app)
        await session.commit()
        app_id = app.id
    await state.clear()
    await message.answer(
        f"✅ Заявку <b>#{app_id}</b> на активність «{item.title}» подано.\n"
        "Починайте виконання після того, як адміністратор підтвердить дозвіл."
    )


@router.callback_query(F.data.startswith("activity_app:"))
async def activity_application_detail(call: CallbackQuery, db: Database) -> None:
    app_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not user or not app or app.user_id != user.id:
            await call.answer("Не знайдено", show_alert=True)
            return
        item = await session.get(ActivityType, app.activity_type_id)
        b = InlineKeyboardBuilder()
        if app.status == "activity_approved":
            b.button(text="📤 Надіслати", callback_data=f"activity_submit:{app.id}")
        elif app.status == "activity_requested":
            b.button(text="❌ Скасувати заявку", callback_data=f"activity_cancel:{app.id}")
        b.button(text="⬅️ Назад", callback_data="nav:activity_mine")
        b.adjust(1)
        text = (
            f"⚡ <b>{item.title if item else 'Активність'}</b>\n"
            f"Статус: <b>{activity_status_label(app.status)}</b>\n"
            f"Нагорода: <b>{app.xp_reward} XP</b> • ⏱ {app.hours_reward:g} год.\n\n"
            f"<b>Ваш план:</b>\n{app.plan_text}\n\n"
            + (f"<b>Результат:</b>\n{app.result_note}\n\n" if app.result_note else "")
            + ("📷 <b>Фото/скріншот додано</b>\n\n" if app.result_image_path else "")
            + (f"<b>Коментар адміністратора:</b>\n{app.admin_note}" if app.admin_note else "")
        )
        proof = await telegram_photo_input(db, app.result_image_path)
        if proof:
            await call.message.answer_photo(proof, caption=text, reply_markup=b.as_markup() if b.buttons else None)
        else:
            await call.message.answer(text, reply_markup=b.as_markup() if b.buttons else None)
    await call.answer()


@router.callback_query(F.data.startswith("activity_submit:"))
async def activity_submit_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    app_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not user or not app or app.user_id != user.id or app.status != "activity_approved":
            await call.answer("Заявка ще не дозволена або вже передана на перевірку", show_alert=True)
            return
    await state.set_state(ActivityApplicationState.result_note)
    await state.update_data(activity_application_id=app_id)
    await call.message.answer("📤 Коротко опишіть, <b>що фактично виконано</b> і який результат отримано. Після цього адміністратор перевірить активність.")
    await call.answer()


@router.message(ActivityApplicationState.result_note)
async def activity_submit_note(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 5:
        await message.answer("Опишіть результат трохи детальніше.")
        return
    await state.update_data(activity_result_note=text)
    await state.set_state(ActivityApplicationState.result_photo)
    b = InlineKeyboardBuilder()
    b.button(text="⏭ Без фото", callback_data="activity_proof_skip")
    await message.answer(
        "📷 <b>Додайте фото або скріншот результату</b> (до 20 МБ).\n"
        "Це допоможе команді підтвердити виконання. Якщо фото немає — натисніть «Без фото».",
        reply_markup=b.as_markup(),
    )


async def _finish_activity_submission(state: FSMContext, db: Database, tg_id: int, image_path: str | None = None) -> bool:
    data = await state.get_data()
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
        app = await session.get(ActivityApplication, int(data.get("activity_application_id") or 0))
        if not user or not app or app.user_id != user.id or app.status != "activity_approved":
            await state.clear()
            return False
        app.result_note = str(data.get("activity_result_note") or "").strip()
        if image_path:
            app.result_image_path = image_path
        app.status = "activity_submitted"
        app.submitted_at = datetime.utcnow()
        await session.commit()
    await state.clear()
    return True


@router.message(ActivityApplicationState.result_photo, F.photo)
async def activity_submit_photo(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    try:
        image_path = await save_telegram_photo(bot, message.photo[-1].file_id, "activity_results", db, max_mb=20)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    if await _finish_activity_submission(state, db, message.from_user.id, image_path):
        await message.answer("⏳ Результат і фото передано адміністратору. Після підтвердження XP і волонтерські години нарахуються автоматично.")


@router.callback_query(ActivityApplicationState.result_photo, F.data == "activity_proof_skip")
async def activity_submit_no_photo(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if await _finish_activity_submission(state, db, call.from_user.id):
        await call.message.answer("⏳ Результат передано адміністратору. Після підтвердження XP і волонтерські години нарахуються автоматично.")
    await call.answer()


@router.message(ActivityApplicationState.result_photo)
async def activity_submit_photo_invalid(message: Message) -> None:
    await message.answer("Надішліть фото/скріншот або натисніть кнопку «⏭ Без фото».")


@router.callback_query(F.data.startswith("activity_cancel:"))
async def activity_cancel(call: CallbackQuery, db: Database) -> None:
    app_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not user or not app or app.user_id != user.id or app.status != "activity_requested":
            await call.answer("Заявку вже не можна скасувати", show_alert=True)
            return
        app.status = "activity_cancelled"
        await session.commit()
    await call.message.answer("❌ Заявку скасовано.")
    await call.answer()


@router.message(F.text.in_({"✅ Волонтерство", "✅ Волонтерські задачі"}))
async def tasks(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        changed = await process_expired_content(session)
        if changed:
            await session.commit()
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            return
        now = datetime.utcnow()
        rows = (
            await session.scalars(
                select(VolunteerTask)
                .where(
                    VolunteerTask.status.in_(["open", "active", "postponed"]),
                    (VolunteerTask.deadline.is_(None)) | (VolunteerTask.deadline >= now),
                )
                .order_by(VolunteerTask.deadline.is_(None), VolunteerTask.deadline.asc(), VolunteerTask.id.desc())
            )
        ).all()
        mine = {
            p.task_id: p
            for p in (await session.scalars(
                select(VolunteerTaskParticipation)
                .where(VolunteerTaskParticipation.user_id == user.id)
            )).all()
        }
        visible = []
        for task in rows:
            count = await session.scalar(
                select(func.count(VolunteerTaskParticipation.id)).where(
                    VolunteerTaskParticipation.task_id == task.id,
                    VolunteerTaskParticipation.status != "cancelled",
                )
            ) or 0
            part = mine.get(task.id)
            if part or (task.status in {"open", "active", "postponed"} and count < max(1, int(task.max_participants or 1))):
                visible.append((task, part, int(count)))
        if not visible:
            await message.answer("✅ Доступних волонтерських задач зараз немає.")
            return
        b = InlineKeyboardBuilder()
        task_lines = []
        for idx, (task, part, count) in enumerate(visible, start=1):
            if part and part.status == "submitted":
                prefix = "⏳"
                state_text = "на перевірці"
            elif part and part.status == "approved":
                prefix = "✅"
                state_text = "підтверджено"
            elif part:
                prefix = "🟡"
                state_text = "ви долучилися"
            else:
                prefix = "🟢"
                state_text = "є місце"
            deadline = task.deadline.strftime("%d.%m.%Y %H:%M") if task.deadline else "без дедлайну"
            task_lines.append(
                f"<b>{idx}. {escape(task.title)}</b>\n{prefix} {state_text} • 👥 {count}/{max(1, int(task.max_participants or 1))} • 📆 {deadline}"
            )
            b.button(
                text=entity_button_text(f"{prefix} {task.title}"),
                callback_data=f"task:{task.id}",
            )
        b.adjust(1)
        await message.answer(
            "✅ <b>Волонтерські задачі</b>\n\n"
            "🟢 є місце • 🟡 ви долучилися • ⏳ на перевірці • ✅ підтверджено\n\n"
            + "\n\n".join(task_lines),
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data.startswith("task:"))
async def task_detail(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        changed = await process_expired_content(session)
        if changed: await session.commit()
        user = await get_user_by_tg(session, call.from_user.id)
        task = await session.get(VolunteerTask, task_id)
        if not user or not task:
            await call.answer("Не знайдено", show_alert=True)
            return
        mine = await session.scalar(
            select(VolunteerTaskParticipation).where(
                VolunteerTaskParticipation.task_id == task.id,
                VolunteerTaskParticipation.user_id == user.id,
            )
        )
        count = await session.scalar(
            select(func.count(VolunteerTaskParticipation.id)).where(
                VolunteerTaskParticipation.task_id == task.id,
                VolunteerTaskParticipation.status != "cancelled",
            )
        ) or 0
        maximum = max(1, int(task.max_participants or 1))
        deadline = task.deadline.strftime("%d.%m.%Y") if task.deadline else "без дедлайну"
        b = InlineKeyboardBuilder()
        is_available = task.status in {"open", "active", "postponed"} and (task.deadline is None or task.deadline >= datetime.utcnow())
        if is_available:
            if not mine and count < maximum:
                b.button(text="🙋 Долучитися", callback_data=f"task_claim:{task.id}")
            elif mine and mine.status in {"joined", "returned"}:
                b.button(text="✅ На перевірку", callback_data=f"task_done:{task.id}")
            elif mine and mine.status == "submitted":
                b.button(text="⏳ Очікує перевірки", callback_data="noop")
            elif mine and mine.status == "approved":
                b.button(text="🏆 Підтверджено", callback_data="noop")
            if mine and mine.status in {"joined", "returned", "submitted"}:
                b.button(text="❌ Скасувати участь", callback_data=f"task_cancel_join:{task.id}")
        b.button(text="⬅️ Назад", callback_data="nav:tasks")
        b.adjust(1)
        text = (
            f"🧰 <b>{task.title}</b>\n"
            f"📆 Дедлайн: {deadline}\n"
            f"👥 Учасники: <b>{count}/{maximum}</b>\n"
            f"⚡ {task.xp_reward} XP • ⏱ {task.hours_reward:g} год.\n\n"
            f"{task.description or 'Без додаткового опису.'}"
        )
        if mine:
            status_names = {"joined":"Виконується", "returned":"Повернуто на доопрацювання", "submitted":"На перевірці", "approved":"Підтверджено"}
            text += f"\n\nВаш статус: <b>{status_names.get(mine.status, mine.status)}</b>"
            if mine.admin_note:
                text += f"\n💬 Коментар координатора: {mine.admin_note}"
        photo = await telegram_photo_input(db, task.image_path)
        if photo:
            await call.message.answer_photo(photo, caption=text, reply_markup=b.as_markup() if b.buttons else None)
        else:
            await call.message.answer(text, reply_markup=b.as_markup() if b.buttons else None)
        await call.answer()


@router.callback_query(F.data.startswith("task_claim:"))
async def task_claim(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        task = await session.get(VolunteerTask, task_id)
        if not user or not task or task.status not in {"open", "active", "postponed"} or (task.deadline and task.deadline < datetime.utcnow()):
            await call.answer("Задача недоступна", show_alert=True)
            return
        existing = await session.scalar(select(VolunteerTaskParticipation).where(
            VolunteerTaskParticipation.task_id == task.id,
            VolunteerTaskParticipation.user_id == user.id,
        ))
        if existing and existing.status != "cancelled":
            await call.answer("Ви вже долучилися до цієї задачі", show_alert=True)
            return
        count = await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(
            VolunteerTaskParticipation.task_id == task.id,
            VolunteerTaskParticipation.status != "cancelled",
        )) or 0
        if count >= max(1, int(task.max_participants or 1)):
            await call.answer("Усі місця вже зайняті", show_alert=True)
            return
        if existing:
            existing.status = "joined"
            existing.joined_at = datetime.utcnow()
            existing.submitted_at = None
            existing.approved_at = None
            existing.admin_note = ""
        else:
            session.add(VolunteerTaskParticipation(task_id=task.id, user_id=user.id, status="joined"))
        await session.commit()
        await call.message.answer(f"✅ Ви долучилися до задачі <b>{task.title}</b>. Після виконання відкрийте її ще раз і надішліть результат на перевірку.")
        await call.answer()


@router.callback_query(F.data.startswith("task_done:"))
async def task_done(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        task = await session.get(VolunteerTask, task_id)
        part = await session.scalar(select(VolunteerTaskParticipation).where(
            VolunteerTaskParticipation.task_id == task_id,
            VolunteerTaskParticipation.user_id == user.id if user else -1,
        ))
        if not user or not task or task.status not in {"open", "active", "postponed"} or (task.deadline and task.deadline < datetime.utcnow()):
            await call.answer("Дедлайн задачі завершено", show_alert=True)
            return
        if not part or part.status not in {"joined", "returned"}:
            await call.answer("Неактуально", show_alert=True)
            return
        part.status = "submitted"
        part.submitted_at = datetime.utcnow()
        await session.commit()
        await call.message.answer("⏳ Виконання передано координатору на підтвердження.")
        await call.answer()


@router.callback_query(F.data.startswith("task_cancel_join:"))
async def task_cancel_join(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer(); return
        part = await session.scalar(select(VolunteerTaskParticipation).where(VolunteerTaskParticipation.task_id == task_id, VolunteerTaskParticipation.user_id == user.id))
        if not part or part.status == "approved":
            await call.answer("Участь уже не можна скасувати", show_alert=True); return
        part.status = "cancelled"
        part.submitted_at = None
        part.admin_note = "Скасовано учасником"
        await session.commit()
    await call.message.answer("❌ Участь у волонтерській задачі скасовано. Історію запису збережено.")
    await call.answer()


@router.callback_query(F.data == "nav:opportunities")
async def nav_opportunities(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        rows=list((await session.scalars(select(Opportunity).where(Opportunity.active == True,(Opportunity.deadline.is_(None)) | (Opportunity.deadline >= datetime.utcnow())).order_by(Opportunity.deadline.asc().nullslast(),Opportunity.id.desc()))).all())  # noqa: E712
        if not user or not rows:
            await call.message.answer("🌍 Зараз немає актуальних можливостей для молоді.")
        else:
            b=InlineKeyboardBuilder(); lines=["🌍 <b>Можливості для молоді</b>","","<b>Оберіть можливість:</b>"]
            for idx,o in enumerate(rows[:20],1):
                deadline=o.deadline.strftime("%d.%m.%Y") if o.deadline else "без дедлайну"
                lines.append(f"\n<b>{idx}. {escape(o.title)}</b>\n📆 {deadline} • {escape(o.kind or 'можливість')}")
                b.button(text=entity_button_text(f"🌍 {o.title}"),callback_data=f"opp:{o.id}")
            b.adjust(1); await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "nav:activities")
async def nav_activities(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        rows=(await session.scalars(select(ActivityType).where(ActivityType.active == True).order_by(ActivityType.sort_order,ActivityType.title))).all()  # noqa: E712
        mine=(await session.scalars(select(ActivityApplication).where(ActivityApplication.user_id==user.id).order_by(ActivityApplication.requested_at.desc()).limit(12))).all()
        b=InlineKeyboardBuilder(); lines=["⚡ <b>Активності АМП XP</b>","","<b>Доступні активності:</b>"]
        for idx,item in enumerate(rows,1):
            lines.append(f"\n<b>{idx}. {escape(item.title)}</b>\n⚡ {item.xp_reward} XP • ⏱ {item.hours_reward:g} год.")
            b.button(text=entity_button_text(f"⚡ {item.title} · {item.xp_reward} XP"),callback_data=f"activity:{item.id}")
        if mine: b.button(text="📋 Мої заявки",callback_data="activity:mine")
        b.adjust(1); await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "nav:activity_mine")
async def nav_activity_mine(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        rows=(await session.execute(select(ActivityApplication,ActivityType).join(ActivityType,ActivityType.id==ActivityApplication.activity_type_id).where(ActivityApplication.user_id==user.id).order_by(ActivityApplication.requested_at.desc()).limit(15))).all()
        b=InlineKeyboardBuilder(); lines=["📋 <b>Мої заявки на активності</b>"]
        for app,item in rows:
            lines.append(f"\n<b>#{app.id} • {item.title}</b>\n{activity_status_label(app.status)} • {app.xp_reward} XP")
            b.button(text=entity_button_text(f"📋 #{app.id} · {item.title}"),callback_data=f"activity_app:{app.id}")
        b.button(text="⬅️ Назад",callback_data="nav:activities"); b.adjust(1)
        await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "nav:tasks")
async def nav_tasks(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        await process_expired_content(session); await session.commit()
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        now=datetime.utcnow(); rows=(await session.scalars(select(VolunteerTask).where(VolunteerTask.status.in_(["open","active","postponed"]),(VolunteerTask.deadline.is_(None)) | (VolunteerTask.deadline>=now)).order_by(VolunteerTask.deadline.is_(None),VolunteerTask.deadline.asc(),VolunteerTask.id.desc()))).all()
        mine={p.task_id:p for p in (await session.scalars(select(VolunteerTaskParticipation).where(VolunteerTaskParticipation.user_id==user.id))).all()}
        b=InlineKeyboardBuilder(); lines=["✅ <b>Волонтерські задачі</b>"]
        for task in rows:
            count=int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.task_id==task.id,VolunteerTaskParticipation.status!="cancelled")) or 0); part=mine.get(task.id)
            if not part and count>=max(1,int(task.max_participants or 1)): continue
            prefix="⏳" if part and part.status=="submitted" else "✅" if part and part.status=="approved" else "🟡" if part else "🟢"
            lines.append(f"\n<b>{escape(task.title)}</b>\n{prefix} • 👥 {count}/{max(1,int(task.max_participants or 1))}")
            b.button(text=entity_button_text(f"{prefix} {task.title}"),callback_data=f"task:{task.id}")
        b.adjust(1); await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.message(F.text == "📊 Рейтинг")
async def leaderboard(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        season = await current_season(session)
        if not user or not season:
            await message.answer("📊 Активний сезон ще не налаштований.")
            return
        sxp = await season_xp(session, user.id, season.id)
        league = league_for_xp(sxp)
        b = InlineKeyboardBuilder()
        b.button(text="🌍 Загальний рейтинг · ТОП-20", callback_data="rating:overall")
        b.button(text=f"{league.icon} Рейтинг моєї ліги", callback_data="rating:league")
        b.adjust(1)
        privacy_note = "\n\n🔒 Твій профіль прихований із публічного рейтингу." if user.leaderboard_opt_in is False else ""
        await message.answer(
            f"📊 <b>Рейтинг сезону «{escape(season.name)}»</b>\n\n"
            f"Твоя ліга: <b>{league.icon} {league.title}</b>\n"
            f"Сезонний XP: <b>{sxp}</b>{privacy_note}",
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data == "rating:overall")
async def rating_overall(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        season = await current_season(session)
        if not season:
            await call.answer("Активного сезону немає", show_alert=True); return
        rows = await season_leaderboard_rows(session, season, limit=20)
        lines = [f"🌍 <b>Загальний ТОП-20 · {escape(season.name)}</b>"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (_, name, xp) in enumerate(rows, 1):
            prefix = medals[i-1] if i <= 3 else f"{i}."
            lg = league_for_xp(int(xp or 0))
            lines.append(f"{prefix} {escape(name)} — <b>{int(xp or 0)} XP</b> · {lg.icon}")
        if len(lines) == 1:
            lines.append("Рейтинг поки порожній.")
        b = InlineKeyboardBuilder()
        b.button(text="🏆 Рейтинг моєї ліги", callback_data="rating:league")
        await call.message.answer("\n".join(lines), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "rating:league")
async def rating_league(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        season = await current_season(session)
        if not user or not season:
            await call.answer("Дані недоступні", show_alert=True); return
        sxp = await season_xp(session, user.id, season.id)
        league = league_for_xp(sxp)
        rows = await league_leaderboard_rows(session, season, league)
        position = next((i for i, row in enumerate(rows, 1) if row[0] == user.id), None)
        place_text = f"<b>{position}</b> із {len(rows)}" if position else "<b>не публікується</b>"
        lines = [
            f"{league.icon} <b>{league.title}</b>",
            f"Твоє місце: {place_text} · <b>{sxp} XP</b>",
            "",
            "<b>ТОП-10 ліги</b>",
        ]
        medals = ["🥇", "🥈", "🥉"]
        for i, (_, name, xp) in enumerate(rows[:10], 1):
            prefix = medals[i-1] if i <= 3 else f"{i}."
            lines.append(f"{prefix} {escape(name)} — <b>{int(xp or 0)} XP</b>")
        if not rows:
            lines.append("У лізі поки немає учасників.")
        b = InlineKeyboardBuilder()
        b.button(text="🌍 Загальний ТОП-20", callback_data="rating:overall")
        await call.message.answer("\n".join(lines), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("assigned_idea:"))
async def assigned_idea_detail(call: CallbackQuery, db: Database) -> None:
    idea_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        idea = await session.get(Idea, idea_id)
        if not user or not idea or (idea.responsible_user_id != user.id and idea.user_id != user.id and user.role not in {"admin", "superadmin", "coordinator"}):
            await call.answer("Немає доступу", show_alert=True); return
        deadline = idea.implementation_deadline.strftime("%d.%m.%Y %H:%M") if idea.implementation_deadline else "не встановлено"
        await call.message.answer(
            f"💡 <b>{escape(idea.title)}</b>\n"
            f"Статус: <b>{escape(idea_status_label(idea.status))}</b>\n"
            f"Прогрес: <b>{int(idea.progress_percent or 0)}%</b>\n"
            f"Дедлайн: {deadline}\n\n"
            f"<b>Проблема / потреба</b>\n{escape(idea.problem or '—')}\n\n"
            f"<b>Що пропонується</b>\n{escape(idea.description or '—')}\n\n"
            f"<b>Завдання</b>\n{escape(idea.project_tasks or '—')}"
        )
    await call.answer()


@router.callback_query(F.data.startswith("assigned_request:"))
async def assigned_request_detail(call: CallbackQuery, db: Database) -> None:
    case_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        case = await session.get(RequestCase, case_id)
        if not user or not case or (case.assigned_user_id != user.id and case.user_id != user.id and user.role not in {"admin", "superadmin", "coordinator"}):
            await call.answer("Немає доступу", show_alert=True); return
        number = case.case_number or f"AMP-{case.created_at.year}-{case.id:04d}"
        deadline = case.response_deadline.strftime("%d.%m.%Y %H:%M") if case.response_deadline else "не встановлено"
        await call.message.answer(
            f"🆘 <b>{escape(number)} · {escape(case.title)}</b>\n"
            f"Статус: <b>{escape(request_status_label(case.status))}</b>\n"
            f"Пріоритет: <b>{escape(label(case.priority))}</b>\n"
            f"Дедлайн: {deadline}\n\n"
            f"{escape(case.description or '—')}"
        )
    await call.answer()


@router.message(F.text == "📜 Правила")
async def rules(message: Message) -> None:
    await message.answer(
        "📜 <b>Правила та авторські права АМП XP</b>\n\n"
        "• XP отримуються лише за підтверджену активність.\n"
        "• У розділі «⚡ Активності» спочатку подається заявка з планом; виконання починається після дозволу координатора, а XP нараховуються після фінального підтвердження.\n"
        "• Загальний XP показує досвід і визначає рівень. Окремий XP-гаманець можна обмінювати на винагороди.\n"
        "• QR події фіксує присутність; XP нараховуються після підтвердження координатором.\n"
        "• Персональний QR-бейдж призначений для ідентифікації учасника та не замінює QR події.\n"
        "• Не можна передавати свій QR або акаунт іншій людині.\n"
        "• За порушення безпеки діє Регламент АМПасадорів, а не система «штрафних балів».\n"
        "• Обмежені можливості можуть враховувати XP, але відбір не базується лише на балах.\n\n"
        "© <b>АМПасадори / Анисівський молодіжний простір</b>. Логотип, айдентика, тексти, макети та створені командою матеріали використовуються для діяльності АМП. Не змінюйте логотип, не використовуйте його для сторонніх зборів, реклами чи комерційних матеріалів без погодження команди. Права третіх осіб на фото, музику, шрифти та інший контент мають бути дотримані."
    )
