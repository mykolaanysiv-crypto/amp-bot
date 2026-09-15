from .participant_common import *  # noqa: F401,F403

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


