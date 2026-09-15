from .admin_common import *  # noqa: F401,F403

@router.callback_query(F.data == "admin:moderation")
async def moderation_panel(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав для модерації", show_alert=True)
            return
        now = datetime.utcnow()
        active_count = int(await session.scalar(select(func.count(BanRecord.id)).where(BanRecord.lifted_at.is_(None), BanRecord.ends_at > now)) or 0)
    b = InlineKeyboardBuilder()
    b.button(text="⛔ Видати бан", callback_data="admin:ban_new")
    b.button(text=f"🔴 Активні бани ({active_count})", callback_data="admin:ban_active")
    b.button(text="🕘 Історія банів", callback_data="admin:ban_history")
    b.adjust(1)
    await call.message.answer(
        "🛡 <b>Модерація спільноти</b>\n\n"
        "Бан видається конкретному учаснику, має причину та строк. Тут можна скоротити строк, зняти бан і переглянути історію рішень.",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:ban_new")
async def moderation_new_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
    await state.set_state(AdminBanState.user_id)
    await call.message.answer("Введіть <b>АМП-код</b> учасника, якого потрібно тимчасово заблокувати. Наприклад: <code>24</code> або <code>АМП-0024</code>.")
    await call.answer()


@router.message(AdminBanState.user_id)
async def moderation_new_user(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip().upper().replace("АМП-", "").replace("AMP-", "")
    try:
        user_id = int(raw.lstrip("0") or "0")
    except ValueError:
        await message.answer("Не вдалося прочитати АМП-код. Приклад: АМП-0024")
        return
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await message.answer("Учасника не знайдено."); return
        if user.role == UserRole.SUPERADMIN.value:
            await message.answer("Суперадміністратора не можна заблокувати."); return
        active = await session.scalar(select(BanRecord).where(BanRecord.user_id == user.id, BanRecord.lifted_at.is_(None), BanRecord.ends_at > datetime.utcnow()))
        if active:
            await message.answer("У цього учасника вже є активний бан. Відкрийте «Активні бани»."); await state.clear(); return
    await state.update_data(user_id=user_id)
    await state.set_state(AdminBanState.days)
    await message.answer(f"👤 <b>{user.full_name}</b>\nНа скільки днів видати бан? Напишіть число від 1 до 365.")


@router.message(AdminBanState.days)
async def moderation_new_days(message: Message, state: FSMContext) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число днів."); return
    if not 1 <= days <= 365:
        await message.answer("Допустимо від 1 до 365 днів."); return
    await state.update_data(days=days)
    await state.set_state(AdminBanState.reason)
    await message.answer("Вкажіть <b>коротку та конкретну причину</b> блокування.")


@router.message(AdminBanState.reason)
async def moderation_new_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    data = await state.get_data()
    reason = (message.text or "").strip()
    if len(reason) < 4:
        await message.answer("Причина занадто коротка. Опишіть порушення конкретніше."); return
    now = datetime.utcnow(); days = int(data["days"]); ends_at = now + timedelta(days=days)
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, int(data["user_id"]))
        if not admin or not user:
            await state.clear(); return
        record = BanRecord(user_id=user.id, issued_by_user_id=admin.id, source="telegram", reason=reason, started_at=now, original_ends_at=ends_at, ends_at=ends_at, updated_at=now)
        session.add(record)
        user.status = UserStatus.BLOCKED.value; user.blocked_until = ends_at; user.block_reason = reason
        await session.flush()
        await log_audit(session, "tg_user_temp_ban", actor_label=admin.full_name, entity_type="ban_record", entity_id=record.id, details=f"АМП-{user.id:04d}; {days} дн.; {reason}")
        await _queue_user_notice(session, user, f"⛔ <b>Ваш профіль тимчасово обмежено</b>\nПричина: {reason}\nСтрок: {days} дн.\nДо: {ends_at.strftime('%d.%m.%Y %H:%M')}", source="moderation", title="Тимчасове обмеження", entity_type="ban_record", entity_id=record.id, dedupe_key=f"ban_notice:{record.id}:issued")
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Бан видано: <b>{user.full_name}</b> до {ends_at.strftime('%d.%m.%Y %H:%M')}.")


@router.callback_query(F.data == "admin:ban_active")
async def moderation_active(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
        rows = (await session.scalars(select(BanRecord).where(BanRecord.lifted_at.is_(None), BanRecord.ends_at > datetime.utcnow()).order_by(BanRecord.ends_at.asc()))).all()
        if not rows:
            await call.message.answer("✅ Активних банів немає."); await call.answer(); return
        for ban in rows[:30]:
            user = await session.get(User, ban.user_id)
            b = InlineKeyboardBuilder()
            b.button(text="⏳ Скоротити", callback_data=f"admin:ban_shorten:{ban.id}")
            b.button(text="✅ Зняти бан", callback_data=f"admin:ban_unban:{ban.id}")
            b.adjust(2)
            await call.message.answer(
                f"⛔ <b>{user.full_name if user else 'Учасник'}</b> • АМП-{ban.user_id:04d}\n"
                f"До: <b>{ban.ends_at.strftime('%d.%m.%Y %H:%M')}</b>\nПричина: {ban.reason}",
                reply_markup=b.as_markup(),
            )
    await call.answer()


@router.callback_query(F.data.startswith("admin:ban_unban:"))
async def moderation_unban_tg(call: CallbackQuery, db: Database, bot: Bot) -> None:
    record_id = int(call.data.rsplit(":", 1)[1]); now = datetime.utcnow()
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        record = await session.get(BanRecord, record_id)
        if not admin or not record or record.lifted_at is not None:
            await call.answer("Запис не знайдено", show_alert=True); return
        user = await session.get(User, record.user_id)
        record.lifted_at = now; record.lift_reason = "Бан знято суперадміністратором у Telegram"; record.updated_at = now
        if user:
            user.status = UserStatus.ACTIVE.value; user.blocked_until = None; user.block_reason = None
        await log_audit(session, "tg_user_unban", actor_label=admin.full_name, entity_type="ban_record", entity_id=record.id, details=record.lift_reason)
        await _queue_user_notice(session, user, "✅ Тимчасове обмеження профілю знято. Ви знову можете користуватися можливостями АМП.", source="moderation", title="Обмеження знято", entity_type="ban_record", entity_id=record.id, dedupe_key=f"ban_notice:{record.id}:lifted")
        await session.commit()
    await call.message.answer("✅ Бан знято.")
    await call.answer()


@router.callback_query(F.data.startswith("admin:ban_shorten:"))
async def moderation_shorten_start_tg(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    record_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
        record = await session.get(BanRecord, record_id)
        if not record or record.lifted_at is not None:
            await call.answer("Бан вже не активний", show_alert=True); return
    await state.update_data(shorten_record_id=record_id)
    await state.set_state(AdminBanState.shorten_days)
    await call.message.answer("На скільки <b>днів від сьогодні</b> залишити бан? Новий строк має бути коротшим за поточний.")
    await call.answer()


@router.message(AdminBanState.shorten_days)
async def moderation_shorten_finish_tg(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    try: days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число днів."); return
    if not 1 <= days <= 365:
        await message.answer("Допустимо від 1 до 365 днів."); return
    data = await state.get_data(); now = datetime.utcnow(); new_end = now + timedelta(days=days)
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        record = await session.get(BanRecord, int(data["shorten_record_id"]))
        if not admin or not record or record.lifted_at is not None:
            await state.clear(); return
        if new_end >= record.ends_at:
            await message.answer("Новий строк не є коротшим за поточний. Вкажіть меншу кількість днів."); return
        user = await session.get(User, record.user_id)
        record.ends_at = new_end; record.updated_at = now
        if user: user.blocked_until = new_end
        await log_audit(session, "tg_user_ban_shorten", actor_label=admin.full_name, entity_type="ban_record", entity_id=record.id, details=f"Новий строк до {new_end.strftime('%d.%m.%Y %H:%M')}")
        await _queue_user_notice(session, user, f"ℹ️ Строк тимчасового обмеження скорочено. Новий строк: до {new_end.strftime('%d.%m.%Y %H:%M')}.", source="moderation", title="Строк обмеження змінено", entity_type="ban_record", entity_id=record.id)
        await session.commit()
    await state.clear(); await message.answer(f"✅ Строк скорочено до {new_end.strftime('%d.%m.%Y %H:%M')}.")


@router.callback_query(F.data == "admin:ban_history")
async def moderation_history_tg(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
        rows = (await session.scalars(select(BanRecord).order_by(BanRecord.started_at.desc()).limit(20))).all()
        if not rows:
            await call.message.answer("Історія банів порожня."); await call.answer(); return
        lines = ["🕘 <b>Останні рішення модерації</b>"]
        now = datetime.utcnow()
        for ban in rows:
            user = await session.get(User, ban.user_id)
            if ban.lifted_at: status = f"завершено {ban.lifted_at.strftime('%d.%m.%Y')}"
            elif ban.ends_at <= now: status = "строк минув"
            else: status = f"активний до {ban.ends_at.strftime('%d.%m.%Y')}"
            lines.append(f"\n• АМП-{ban.user_id:04d} {user.full_name if user else ''}\n  {status} • {ban.reason}")
        await call.message.answer("\n".join(lines))
    await call.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Скасовано.")


