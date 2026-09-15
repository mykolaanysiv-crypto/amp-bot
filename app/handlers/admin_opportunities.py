from .admin_common import *  # noqa: F401,F403

@router.callback_query(F.data == "admin:create_opportunity")
async def opp_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminOpportunityState.title)
    await call.message.answer("📰 Назва можливості?")
    await call.answer()


@router.message(AdminOpportunityState.title)
async def opp_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminOpportunityState.kind)
    await message.answer("Тип: навчання / обмін / конкурс / волонтерство / інше?")


@router.message(AdminOpportunityState.kind)
async def opp_kind(message: Message, state: FSMContext) -> None:
    await state.update_data(kind=(message.text or "").strip())
    await state.set_state(AdminOpportunityState.description)
    await message.answer("Короткий опис?")


@router.message(AdminOpportunityState.description)
async def opp_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminOpportunityState.deadline)
    await message.answer("Дедлайн ДД.ММ.РРРР або <b>немає</b>.")


@router.message(AdminOpportunityState.deadline)
async def opp_deadline(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().lower()
    deadline = None
    if raw != "немає":
        try:
            deadline = datetime.strptime(raw, "%d.%m.%Y")
        except ValueError:
            await message.answer("Формат ДД.ММ.РРРР або «немає».")
            return
    await state.update_data(deadline=deadline.isoformat() if deadline else None)
    await state.set_state(AdminOpportunityState.url)
    await message.answer("Посилання або <b>немає</b>.")


@router.message(AdminOpportunityState.url)
async def opp_finish(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "opportunities.manage"):
        await state.clear()
        return
    data = await state.get_data()
    raw = (message.text or "").strip()
    url = None if raw.lower() == "немає" else raw
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            return
        item=Opportunity(title=data["title"], kind=data["kind"], direction=data["kind"], description=data["description"], deadline=datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None, url=url)
        session.add(item); await session.flush()
        matched = await refresh_matches_for_opportunity(session, item)
        await log_audit(session, "telegram_opportunity_create", actor=admin, entity_type="opportunity", entity_id=item.id, details=f"matches={matched}")
        await session.commit()
    await state.clear()
    await message.answer("✅ Можливість опубліковано.")


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(call: CallbackQuery, db: Database, settings: Settings) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав для розсилок", show_alert=True)
            return
    await call.message.answer(
        "📣 <b>Комунікаційний центр АМП</b>\n\n"
        "У вебпанелі можна обрати аудиторію, використати шаблон, переглянути повідомлення перед відправкою та бачити історію доставок.\n\n"
        f"🌐 {settings.public_base_url}/admin/broadcasts"
    )
    await call.answer()


@router.callback_query(F.data == "admin:export")
async def export_data(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        content = await export_excel(session)
    await call.message.answer_document(
        BufferedInputFile(content, filename=f"AMP_XP_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"),
        caption="📈 Експорт учасників, XP-журналу та подій.",
    )
    await call.answer()


@router.message(Command("setrole"))
async def set_role(message: Message, db: Database, bot: Bot) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer(
            "Формат: <code>/setrole 24 ампасадор</code>\n"
            "Ролі: <b>учасник, ампасадор, координатор, адміністратор</b>."
        )
        return
    try:
        target_id = int(parts[1].replace("АМП-", "").replace("AMP-", "").lstrip("0") or "0")
    except ValueError:
        await message.answer("Некоректний номер.")
        return
    role_aliases = {
        "учасник": UserRole.PARTICIPANT.value, "participant": UserRole.PARTICIPANT.value,
        "ампасадор": UserRole.AMBASSADOR.value, "ambassador": UserRole.AMBASSADOR.value,
        "координатор": UserRole.COORDINATOR.value, "coordinator": UserRole.COORDINATOR.value,
        "адміністратор": UserRole.ADMIN.value, "admin": UserRole.ADMIN.value,
    }
    new_role = role_aliases.get(parts[2].lower())
    if not new_role:
        await message.answer("Невідома роль. Використай: учасник, ампасадор, координатор або адміністратор.")
        return
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin or not has_permission(admin.role, admin.staff_permissions_json, "security.manage"):
            await message.answer("⛔ Недостатньо прав для зміни ролей.")
            return
        user = await session.get(User, target_id)
        if not user:
            await message.answer("Користувача не знайдено.")
            return
        old_role = user.role
        user.role = new_role
        if old_role != new_role:
            # Role changes reset any custom ACL so permissions cannot silently
            # survive a demotion/promotion. Superadmin can assign a new set in web.
            user.staff_permissions_json = None
            await log_audit(
                session, "telegram_user_role_change", actor=admin, entity_type="user", entity_id=user.id,
                details=f"{old_role}->{new_role}; permissions=role_defaults",
            )
        await _queue_user_notice(session, user, f"🔐 Вашу роль змінено на <b>{label(new_role)}</b>. Відкрийте /menu.", source="system", title="Зміна ролі", entity_type="user", entity_id=user.id)
        await session.commit()
        await message.answer(f"✅ {user.full_name}: роль → {label(new_role)}.")


