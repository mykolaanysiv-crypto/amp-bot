from ..time_utils import clock
from .admin_common import (
    AdminXPState, Bot, CallbackQuery, ConsentHistory, Database, F, FSMContext, InlineKeyboardBuilder, Message, Settings, User, UserStatus, _admin, _queue_user_notice, _require_admin, _require_permission, _staff_permissions, add_active_users_to_default_team, add_xp, admin_menu, admin_section_menu, analytics_bot_text, build_analytics, log_audit, normalize_manual_xp, pending_user_keyboard, reward_referral_if_ready, router, select
)

_ADMIN_SECTION_TITLES = {
    "events": "📅 Події",
    "activities": "🎯 Активності",
    "gamification": "🏆 XP та винагороди",
    "people": "👥 Учасники",
    "data": "📊 Аналітика й комунікація",
}


@router.message(F.text == "🛠 Адмін-панель")
async def admin_panel(message: Message, db: Database) -> None:
    admin = await _require_admin(message, db)
    if not admin:
        return
    await message.answer(
        "🛠 <b>Панель адміністратора АМПасадорів</b>\n\nОберіть потрібний розділ:",
        reply_markup=admin_menu(admin.role, _staff_permissions(admin)),
    )


async def _show_admin_menu(call: CallbackQuery, db: Database, *, section: str | None = None) -> None:
    admin = await _require_admin(call, db)
    if not admin:
        return
    if section and section not in _ADMIN_SECTION_TITLES:
        await call.answer("Невідомий розділ", show_alert=True)
        return

    if section:
        text = f"{_ADMIN_SECTION_TITLES[section]}\n\nОберіть дію:"
        markup = admin_section_menu(admin.role, section, _staff_permissions(admin))
    else:
        text = "🛠 <b>Панель адміністратора АМПасадорів</b>\n\nОберіть потрібний розділ:"
        markup = admin_menu(admin.role, _staff_permissions(admin))
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        await call.message.answer(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "admin:menu")
async def admin_menu_root(call: CallbackQuery, db: Database) -> None:
    await _show_admin_menu(call, db)


@router.callback_query(F.data.startswith("admin:section:"))
async def admin_menu_section(call: CallbackQuery, db: Database) -> None:
    await _show_admin_menu(call, db, section=call.data.rsplit(":", 1)[-1])


@router.callback_query(F.data == "admin:analytics")
async def admin_analytics(call: CallbackQuery, db: Database, settings: Settings) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Аналітика доступна адміністраторам", show_alert=True)
            return
        data = await build_analytics(session)
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Повна аналітика", url=f"{settings.public_base_url}/admin/analytics")
    builder.adjust(1)
    await call.message.answer(analytics_bot_text(data), reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data == "admin:web")
async def web_admin_link(call: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _require_admin(call, db):
        return
    await call.message.answer(
        "🌐 <b>Вебпанель адміністратора АМПасадорів</b>\n"
        f"{settings.public_base_url}/admin\n\n"
        "Доступ керується через захищені персональні web-акаунти. Паролі зберігаються лише як хеші у БД.\n"
        "Зміна пароля та 2FA: <code>/admin/account</code>."
    )
    await call.answer()


@router.callback_query(F.data == "admin:pending")
async def pending_users(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав для цієї дії", show_alert=True)
            return
        users = (await session.scalars(select(User).where(User.status == UserStatus.PENDING.value).order_by(User.created_at))).all()
        if not users:
            await call.message.answer("👥 Нових заявок немає.")
            await call.answer()
            return
        for u in users[:30]:
            age_text = u.birth_date.strftime("%d.%m.%Y") if u.birth_date else "—"
            consent = "потрібна" if u.parental_consent_required and not u.parental_consent_confirmed else "не потрібна / підтверджена"
            await call.message.answer(
                f"👤 <b>{u.full_name}</b>\nАМП-код: <code>АМП-{u.id:04d}</code>\n"
                f"Дата народження: {age_text}\nНаселений пункт: {u.settlement or '—'}\n"
                f"Згода батьків: {consent}",
                reply_markup=pending_user_keyboard(u.id, u.parental_consent_required and not u.parental_consent_confirmed, _staff_permissions(admin)),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:consent:"))
async def confirm_consent(call: CallbackQuery, db: Database) -> None:
    user_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await call.answer("Не знайдено", show_alert=True)
            return
        user.parental_consent_confirmed = True
        user.parental_consent_status = "received"
        user.parental_consent_received_at = clock.storage_utc()
        session.add(ConsentHistory(
            user_id=user.id,
            consent_type="parental",
            status="received",
            file_path=user.parental_consent_file_path,
            changed_by_label=admin.full_name or "Telegram admin",
            changed_at=user.parental_consent_received_at,
        ))
        await session.commit()
        await call.message.answer(f"👪 Згоду батьків для <b>{user.full_name}</b> позначено як підтверджену.")
        await call.answer()


@router.callback_query(F.data.startswith("admin:approve:"))
async def approve_user(call: CallbackQuery, db: Database, bot: Bot, settings: Settings) -> None:
    user_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await call.answer("Не знайдено", show_alert=True)
            return
        if user.parental_consent_required and not user.parental_consent_confirmed:
            await call.answer("Спочатку підтвердьте згоду батьків", show_alert=True)
            return
        user.status = UserStatus.ACTIVE.value
        user.registration_review_status = "approved"
        user.registration_reviewed_at = clock.storage_utc()
        user.registration_reviewed_by = admin.full_name or f"Telegram:{admin.tg_id}"
        user.registration_rejection_reason = None
        await add_active_users_to_default_team(session)
        referral_reward = await reward_referral_if_ready(session, user, settings, created_by=admin.id)
        await log_audit(session, "user_activated", admin, entity_type="user", entity_id=user.id)
        await _queue_user_notice(session, user, "✅ Ваш профіль АМП XP активовано! Відкрийте /menu.", source="user_activation", entity_type="user", entity_id=user.id, dedupe_key=f"user_activation:{user.id}")
        if referral_reward:
            inviter, reward = referral_reward
            await _queue_user_notice(
                session, inviter,
                f"🤝 Твоє запрошення спрацювало! <b>{user.full_name}</b> активовано. +{reward} XP.\n"
                "Бонус за запрошення зменшується від 10 до 1 XP у межах кварталу та оновлюється на початку нового кварталу.",
                source="referral", entity_type="user", entity_id=user.id, dedupe_key=f"referral_reward_notice:{user.id}:{inviter.id}",
            )
        await session.commit()
        await call.message.answer(f"✅ <b>{user.full_name}</b> активовано.")
        await call.answer()


@router.callback_query(F.data.startswith("admin:block:"))
async def block_user(call: CallbackQuery, db: Database, bot: Bot) -> None:
    user_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await call.answer("Не знайдено", show_alert=True)
            return
        user.status = UserStatus.BLOCKED.value
        await _queue_user_notice(session, user, "⛔ Ваш профіль АМП XP заблоковано. Зверніться до команди АМП.", source="moderation", entity_type="user", entity_id=user.id, dedupe_key=f"user_blocked:{user.id}:{clock.storage_utc().date().isoformat()}")
        await session.commit()
        await call.answer("Заблоковано")


@router.callback_query(F.data == "admin:add_xp")
async def add_xp_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminXPState.user_id)
    await call.message.answer("⚡ Вкажіть числовий номер учасника (наприклад <code>24</code> для АМП-0024).")
    await call.answer()


@router.message(AdminXPState.user_id)
async def add_xp_user(message: Message, state: FSMContext, db: Database) -> None:
    try:
        user_id = int((message.text or "").replace("АМП-", "").replace("AMP-", "").lstrip("0") or "0")
    except ValueError:
        await message.answer("Вкажіть числовий номер.")
        return
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer("Учасника не знайдено.")
            return
    await state.update_data(user_id=user_id)
    await state.set_state(AdminXPState.amount)
    await message.answer("Скільки XP нарахувати? Ручний позитивний бонус — до 40 XP за одну підтверджену дію. Від’ємне число можна використати для корекції.")


@router.message(AdminXPState.amount)
async def add_xp_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число, наприклад 20.")
        return
    normalized = normalize_manual_xp(amount)
    if normalized != amount:
        if amount > 40:
            await message.answer("⚖️ Для балансу ручний позитивний бонус обмежено 40 XP за одну дію. Значення буде встановлено на 40 XP.")
        elif amount < -500:
            await message.answer("Для безпеки корекцію обмежено -500 XP за одну операцію.")
    await state.update_data(amount=normalized)
    await state.set_state(AdminXPState.description)
    await message.answer("Напишіть причину / опис нарахування.")


@router.message(AdminXPState.description)
async def add_xp_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "xp.award"):
        await state.clear()
        return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, data["user_id"])
        if not admin or not user:
            await state.clear()
            return
        total, level, leveled = await add_xp(
            session, user, data["amount"], (message.text or "").strip(), created_by=admin.id
        )
        text = f"⚡ Вам нараховано <b>{data['amount']} XP</b>\nПричина: {(message.text or '').strip()}\nВсього: <b>{total} XP</b>"
        if leveled:
            text += f"\n\n🎉 Новий рівень: <b>{level}</b>"
        await _queue_user_notice(session, user, text, source="xp_achievement", title="Нарахування XP", entity_type="user", entity_id=user.id)
        await session.commit()
        await message.answer(f"✅ {user.full_name}: {data['amount']} XP. Загалом {total} XP.")
    await state.clear()


