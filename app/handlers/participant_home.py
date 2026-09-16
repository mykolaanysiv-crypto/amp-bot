from ..time_utils import clock
from .participant_common import (
    AMBASSADOR_BADGE_ROLES, Badge, CallbackQuery, Database, Event, EventFeedback, EventRegistration, F, FSMContext, InlineKeyboardBuilder, InlineKeyboardButton, InlineKeyboardMarkup, LEVELS, Message, OpportunityMatch, Quest, QuestParticipation, RequestCase, RequestMessage, Reward, RewardClaim, StreakFreezeState, UserBadge, UserStatus, XPTransaction, active_month_streak, create_streak_freeze, current_season, escape, func, get_level, get_registration_journey, get_runtime_int, get_user_by_tg, goals_for_user, join_hub_keyboard, label, league_for_xp, log_audit, log_extra, logging, main_menu, more_hub_keyboard, participant_first_name, profile_hub_keyboard, progress_text, refresh_user_streak, restore_super_streak, rewards_keyboard, router, season_xp, select, streak_freeze_summary, telegram_photo_input, timedelta, xp_total
)

@router.message(F.text.in_({"🏠 Головна", "🏠 Огляд"}))
async def overview(message: Message, db: Database) -> None:
    """Participant home: a concise, useful snapshot of what matters today."""
    now_utc = clock.now_utc()
    storage_now = clock.storage_utc(now_utc)
    local_now = clock.local_wall(now_utc)
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            journey = await get_registration_journey(session, message.from_user.id)
            if journey and journey.current_step not in {"submitted", "approved", "first_activity"}:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Продовжити реєстрацію", callback_data="reg:resume")]])
                await message.answer(
                    "🎯 <b>Наступний крок</b>\n\nТвоя реєстрація ще не завершена. Продовж із місця, де зупинився/зупинилася.",
                    reply_markup=kb,
                )
            elif user and user.status == UserStatus.PENDING.value:
                await message.answer("⏳ Реєстрацію надіслано. Профіль очікує підтвердження команди АМП.")
            else:
                await message.answer("Профіль ще не активований. Натисніть /start")
            return
        xp = await xp_total(session, user.id)
        sxp = await season_xp(session, user.id)
        season = await current_season(session)
        streak_row, _ = await refresh_user_streak(session, user)
        league = league_for_xp(sxp)
        level_name, next_threshold = get_level(xp)
        next_event = await session.scalar(
            select(Event).where(Event.status == "open", Event.starts_at >= local_now).order_by(Event.starts_at.asc()).limit(1)
        )
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        today_event = await session.scalar(
            select(Event)
            .join(EventRegistration, EventRegistration.event_id == Event.id)
            .where(
                EventRegistration.user_id == user.id,
                EventRegistration.status.in_(["registered", "reserved", "checked_in", "attended"]),
                Event.starts_at >= day_start, Event.starts_at < day_end,
                Event.status.in_(["open", "postponed", "completed"]),
            )
            .order_by(Event.starts_at.asc()).limit(1)
        )
        pending_feedback = await session.scalar(
            select(EventFeedback)
            .where(EventFeedback.user_id == user.id, EventFeedback.status.in_(["pending", "in_progress"]))
            .order_by(EventFeedback.prompted_at.asc().nullsfirst(), EventFeedback.id.asc()).limit(1)
        )
        next_quest = await session.scalar(
            select(Quest)
            .join(QuestParticipation, QuestParticipation.quest_id == Quest.id)
            .where(
                QuestParticipation.user_id == user.id,
                QuestParticipation.status.in_(["joined", "returned", "completed"]),
                Quest.status.in_(["open", "active", "postponed"]),
                Quest.ends_at.is_not(None),
                Quest.ends_at >= local_now,
            )
            .order_by(Quest.ends_at.asc()).limit(1)
        )
        # A request message stays "new" until the participant opens that case.
        # This is more precise than treating every need_info case as unread.
        open_cases = list((await session.scalars(
            select(RequestCase).where(
                RequestCase.user_id == user.id,
                RequestCase.status != "case_closed",
            ).order_by(RequestCase.updated_at.desc()).limit(30)
        )).all())
        case_updates = 0
        for case in open_cases:
            seen_after = case.participant_last_viewed_at or case.created_at
            unread_admin = await session.scalar(
                select(func.count(RequestMessage.id)).where(
                    RequestMessage.case_id == case.id,
                    RequestMessage.sender_type == "admin",
                    RequestMessage.created_at > seen_after,
                )
            )
            if int(unread_admin or 0) > 0:
                case_updates += 1
        new_matches = int(await session.scalar(
            select(func.count(OpportunityMatch.id)).where(
                OpportunityMatch.user_id == user.id,
                OpportunityMatch.status.in_(["matched", "notified"]),
                OpportunityMatch.matched_at >= storage_now - timedelta(days=7),
            )
        ) or 0)
        goal_rows = await goals_for_user(session, user, now=storage_now)
        near_goal = max(
            (row for row in goal_rows if 70 <= float(row.get("percent") or 0) < 100),
            key=lambda row: float(row.get("percent") or 0),
            default=None,
        )
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
        delta = next_quest.ends_at - local_now
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

    lines.extend(["", "🎯 <b>Наступний крок</b>"])
    if pending_feedback:
        lines.append("⭐ Заверши короткий відгук після події — залишилося кілька натискань. Відкрий останнє повідомлення про відгук.")
    elif today_event:
        lines.append(f"📅 Сьогодні твоя подія: <b>{escape(today_event.title)}</b> о {today_event.starts_at.strftime('%H:%M')}. Перевір деталі у «Долучитися». ")
    elif case_updates:
        lines.append("🆘 Команда АМП очікує твоєї відповіді у зверненні. Відкрий «Звернення».")
    elif near_goal:
        goal = near_goal["goal"]
        lines.append(f"🏁 Ти вже виконав(ла) <b>{near_goal['percent']:.0f}%</b> цілі «{escape(goal.title)}». Ще трохи — і готово.")
    elif next_event:
        lines.append(f"📅 Подивись найближчу подію «{escape(next_event.title)}» та долучайся, якщо вона тобі підходить.")
    else:
        lines.append("🌍 Переглянь актуальні можливості або обери активність у «Долучитися».")
    await message.answer("\n".join(lines), reply_markup=main_menu(user.role, user.staff_permissions_json))


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
            f"АМП-код: <code>АМП-{user.id:04d}</code>\n\n"
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
                    try:
                        await target.answer_photo(photo, caption=f"{badge.icon} <b>{badge.name}</b>\n{badge.description}")
                    except Exception as exc:
                        logging.getLogger("amp.participant_home").debug(
                            "Не вдалося надіслати зображення бейджа",
                            extra=log_extra("TG_BADGE_PHOTO_SEND_FAILED", badge_id=badge.id, exception_type=type(exc).__name__),
                        )


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
            existing.requested_at = clock.storage_utc()
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


