from aiogram.filters import Command
from ..time_utils import clock
from ..opportunity_utils import deadline_urgency, opportunity_sort_key
from .participant_common import (
    CallbackQuery, Database, F, InlineKeyboardBuilder, Message, OPPORTUNITY_INTERESTS, Opportunity, OpportunityInterest, OpportunityMatch, UserStatus, active_month_streak, content_view_stat, datetime, entity_button_text, escape, get_user_by_tg, goals_for_user, log_extra, logging, record_content_view, refresh_matches_for_user, router, select, set_user_interests, telegram_photo_input, user_interests
)

@router.message(Command("smart"))
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
                (Opportunity.deadline.is_(None)) | (Opportunity.deadline >= clock.local_wall()),
            )
        )).all())
        rows.sort(key=opportunity_sort_key)
        await session.commit()
        if not rows:
            await message.answer("🌍 Зараз немає актуальних можливостей для молоді.")
            return
        b = InlineKeyboardBuilder()
        interests = user_interests(user)
        lines = [
            "🌍 <b>Можливості для молоді</b>",
            "Список автоматично впорядковано за актуальністю та дедлайном.",
            f"🎯 Інтереси: <b>{', '.join(interests) if interests else 'ще не обрано'}</b>",
            "",
            "<b>Оберіть можливість:</b>",
        ]
        for idx, o in enumerate(rows[:20], start=1):
            deadline = o.deadline.strftime("%d.%m.%Y") if o.deadline else "без дедлайну"
            score = matched_ids.get(o.id)
            urgent = bool(deadline_urgency(o).get("urgent"))
            prefix = f"✨ Збіг {score}% · " if score else ""
            urgent_text = f"\n🔥 <b>У вас є остання можливість долучитись до «{escape(o.title)}»</b>" if urgent else ""
            lines.append(f"\n<b>{idx}. {escape(o.title)}</b>\n{prefix}📆 {deadline} • {escape(o.kind or 'можливість')}{urgent_text}")
            label_text = f"🔥 {o.title}" if urgent else (f"✨ {o.title}" if score else f"🌍 {o.title}")
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
            "⚙️ <b>Інтереси для персонального підбору можливостей</b>\n\n"
            "Обери теми, які тобі цікаві. Підбір використовує лише вік, ці інтереси, населений пункт, формат і дедлайн. "
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
        except Exception as exc:
            logging.getLogger("amp.participant_opportunities").debug(
                "Не вдалося оновити кнопки інтересів",
                exc_info=exc,
                extra=log_extra("TG_OPP_PREF_MARKUP_EDIT_FAILED", tg_id=call.from_user.id),
            )
    await call.answer("Збережено")


@router.callback_query(F.data == "opp_pref_done")
async def opportunity_preferences_done(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        selected = user_interests(user) if user else []
    await call.message.answer(f"✅ Інтереси збережено: <b>{', '.join(selected) if selected else 'не обрано'}</b>\n\nНові персональні можливості надходитимуть автоматично.")
    await call.answer()


@router.callback_query(F.data.regexp(r"^opp:\d+$"))
async def opportunity_detail(call: CallbackQuery, db: Database) -> None:
    opportunity_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(Opportunity, opportunity_id)
        if not user or not item or not item.active or (item.deadline and clock.local_wall_to_utc(item.deadline) < clock.now_utc()):
            await call.answer("Можливість уже неактуальна", show_alert=True)
            return
        await record_content_view(session, "opportunity", item.id, user=user)
        await session.flush()
        view_stat = await content_view_stat(session, "opportunity", item.id)
        interest = await session.scalar(select(OpportunityInterest).where(OpportunityInterest.opportunity_id == item.id, OpportunityInterest.user_id == user.id))
        match = await session.scalar(select(OpportunityMatch).where(OpportunityMatch.opportunity_id == item.id, OpportunityMatch.user_id == user.id))
        await session.commit()
        age_text = ""
        if item.age_min is not None or item.age_max is not None:
            age_text = f"\n🎂 Вік: {item.age_min if item.age_min is not None else '—'}–{item.age_max if item.age_max is not None else '—'}"
        deadline = item.deadline.strftime("%d.%m.%Y %H:%M") if item.deadline else "без дедлайну"
        link = f"\n🔗 {escape(item.url)}" if item.url else ""
        match_text = f"\n✨ Персональний збіг: <b>{match.score}%</b>" if match else ""
        place_text = f"\n📍 Для: {escape(item.target_settlements)}" if item.target_settlements else ""
        safe_title = escape(item.title or "Можливість")
        urgent = bool(deadline_urgency(item).get("urgent"))
        urgency_text = f"🔥 <b>У вас є остання можливість долучитись до «{safe_title}»</b>\n\n" if urgent else ""
        text = (
            urgency_text +
            f"🌍 <b>{safe_title}</b>\n"
            f"🏷 {escape(item.kind or 'можливість')} • {escape(item.direction or 'Інше')}\n"
            f"💻 Формат: {escape(item.format or 'Онлайн/офлайн')}{age_text}{place_text}{match_text}\n"
            f"📆 Дедлайн: {deadline}\n"
            f"👁 Переглядів: <b>{view_stat['views']}</b>\n\n{escape(item.description or 'Без додаткового опису.')}{link}"
        )
        b = InlineKeyboardBuilder()
        if interest and interest.status == "interested":
            b.button(text="💔 Не цікаво", callback_data=f"opp_uninterest:{item.id}")
        else:
            b.button(text="💙 Мені цікаво", callback_data=f"opp_interest:{item.id}")
        b.button(text="⬅️ Назад", callback_data="nav:opportunities")
        b.adjust(1)
        photo = await telegram_photo_input(db, item.image_path)
        if photo:
            # Telegram limits media captions; keep the full opportunity text readable.
            if len(text) <= 950:
                await call.message.answer_photo(photo, caption=text, reply_markup=b.as_markup())
            else:
                await call.message.answer_photo(photo, caption=f"🌍 <b>{safe_title}</b>\n👁 {view_stat['views']} переглядів")
                await call.message.answer(text, reply_markup=b.as_markup())
        else:
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
            row.status = "interested"; row.updated_at = clock.storage_utc()
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
            row.status = "not_interested"; row.updated_at = clock.storage_utc(); await session.commit()
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
                    except Exception as exc:
                        logging.getLogger("amp.participant_opportunities").warning(
                            "Не вдалося надіслати фото можливості; fallback на текст",
                            exc_info=exc,
                            extra=log_extra("TG_OPPORTUNITY_PHOTO_SEND_FAILED", tg_id=message.from_user.id, opportunity_id=g.id),
                        )
            await message.answer(text)


