from .admin_common import *  # noqa: F401,F403

@router.callback_query(F.data == "admin:activity_apps")
async def admin_activity_apps(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        rows = (await session.execute(
            select(ActivityApplication, ActivityType, User)
            .join(ActivityType, ActivityType.id == ActivityApplication.activity_type_id)
            .join(User, User.id == ActivityApplication.user_id)
            .where(ActivityApplication.status.in_(["activity_requested", "activity_submitted", "activity_approved"]))
            .order_by(ActivityApplication.requested_at.asc())
            .limit(30)
        )).all()
        if not rows:
            await call.message.answer("⚡ Немає заявок на активності, які потребують дії адміністратора.")
            await call.answer()
            return
        for app, item, user in rows:
            b = InlineKeyboardBuilder()
            if app.status == "activity_requested":
                b.button(text="✅ Дозволити", callback_data=f"admin:activity_approve:{app.id}")
                b.button(text="❌ Відхилити", callback_data=f"admin:activity_reject:{app.id}")
            elif app.status == "activity_submitted":
                b.button(text="🏁 Підтвердити", callback_data=f"admin:activity_complete:{app.id}")
                b.button(text="↩ Повернути", callback_data=f"admin:activity_return:{app.id}")
            elif app.status == "activity_approved":
                b.button(text="🏁 Підтвердити", callback_data=f"admin:activity_complete:{app.id}")
            b.adjust(1)
            result = f"\n\n📤 Результат:\n{app.result_note}" if app.result_note else ""
            await call.message.answer(
                f"⚡ <b>#{app.id} • {item.title}</b>\n"
                f"👤 {user.full_name}\n"
                f"Статус: <b>{activity_status_label(app.status)}</b>\n"
                f"🎁 {app.xp_reward} XP • ⏱ {app.hours_reward:g} год.\n\n"
                f"📝 План:\n{app.plan_text}{result}",
                reply_markup=b.as_markup(),
            )
    await call.answer()


@router.callback_query(F.data.startswith("admin:activity_approve:"))
async def admin_activity_approve(call: CallbackQuery, db: Database, bot: Bot) -> None:
    app_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not admin or not app or app.status != "activity_requested":
            await call.answer("Неактуально", show_alert=True)
            return
        item = await session.get(ActivityType, app.activity_type_id)
        user = await session.get(User, app.user_id)
        app.status = "activity_approved"
        app.approved_at = datetime.utcnow()
        app.reviewed_by = admin.id
        await log_audit(session, "tg_activity_approve", admin, entity_type="activity_application", entity_id=app.id, details=item.title if item else "")
        if user and item:
            await _queue_user_notice(session, user, f"✅ Заявку на активність <b>{item.title}</b> погоджено. Можна виконувати. Після завершення відкрийте «⚡ Активності → Мої заявки» і передайте результат на перевірку.", source="activity", title="Активність погоджено", entity_type="activity_application", entity_id=app.id, dedupe_key=f"activity_approved:{app.id}")
        await session.commit()
    await call.answer("Дозволено")


@router.callback_query(F.data.startswith("admin:activity_reject:"))
async def admin_activity_reject(call: CallbackQuery, db: Database, bot: Bot) -> None:
    app_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not admin or not app or app.status != "activity_requested":
            await call.answer("Неактуально", show_alert=True)
            return
        item = await session.get(ActivityType, app.activity_type_id)
        user = await session.get(User, app.user_id)
        app.status = "activity_rejected"
        app.reviewed_by = admin.id
        await log_audit(session, "tg_activity_reject", admin, entity_type="activity_application", entity_id=app.id, details=item.title if item else "")
        if user and item:
            await _queue_user_notice(session, user, f"❌ Заявку на активність <b>{item.title}</b> не погоджено. За потреби обговоріть формат із координатором і подайте нову заявку.", source="activity", title="Активність не погоджено", entity_type="activity_application", entity_id=app.id, dedupe_key=f"activity_rejected:{app.id}")
        await session.commit()
    await call.answer("Відхилено")


@router.callback_query(F.data.startswith("admin:activity_return:"))
async def admin_activity_return(call: CallbackQuery, db: Database, bot: Bot) -> None:
    app_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not admin or not app or app.status != "activity_submitted":
            await call.answer("Неактуально", show_alert=True)
            return
        item = await session.get(ActivityType, app.activity_type_id)
        user = await session.get(User, app.user_id)
        app.status = "activity_approved"
        app.submitted_at = None
        app.reviewed_by = admin.id
        await log_audit(session, "tg_activity_return", admin, entity_type="activity_application", entity_id=app.id, details=item.title if item else "")
        if user and item:
            await _queue_user_notice(session, user, f"↩ Результат активності <b>{item.title}</b> повернуто до виконання/уточнення. Після доопрацювання подайте результат повторно.", source="activity", title="Активність повернено", entity_type="activity_application", entity_id=app.id)
        await session.commit()
    await call.answer("Повернуто")


@router.callback_query(F.data.startswith("admin:activity_complete:"))
async def admin_activity_complete(call: CallbackQuery, db: Database, bot: Bot) -> None:
    app_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        app = await session.get(ActivityApplication, app_id)
        if not admin or not app:
            await call.answer("Неактуально", show_alert=True)
            return
        item = await session.get(ActivityType, app.activity_type_id)
        result = await complete_activity_application(session, app, admin)
        if not result:
            await call.answer("Активність не готова до підтвердження", show_alert=True)
            return
        user, total, level, leveled = result
        await log_audit(session, "tg_activity_complete", admin, entity_type="activity_application", entity_id=app.id, details=f"{item.title if item else 'Активність'}; +{app.xp_reward} XP")
        await _queue_user_notice(session, user, f"🏁 Активність <b>{item.title if item else 'Активність'}</b> підтверджено!\n⚡ +{app.xp_reward} XP • ⏱ +{app.hours_reward:g} год.\nЗагальний досвід: <b>{total} XP</b>\nРівень: {level}", source="xp_achievement", title="Активність підтверджено", entity_type="activity_application", entity_id=app.id, dedupe_key=f"activity_completed:{app.id}")
        await session.commit()
    await call.answer("XP нараховано")


@router.callback_query(F.data == "admin:create_task")
async def task_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminTaskState.title)
    await call.message.answer("🧰 Назва волонтерської задачі?")
    await call.answer()


@router.message(AdminTaskState.title)
async def task_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminTaskState.description)
    await message.answer("Опис задачі?")


@router.message(AdminTaskState.description)
async def task_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminTaskState.xp_reward)
    await message.answer("XP за виконання? Допустимо 10–40 XP залежно від складності та тривалості.")


@router.message(AdminTaskState.xp_reward)
async def task_xp(message: Message, state: FSMContext) -> None:
    try:
        xp = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть число.")
        return
    await state.update_data(xp_reward=xp)
    await state.set_state(AdminTaskState.hours_reward)
    await message.answer("Волонтерські години за виконання?")


@router.message(AdminTaskState.hours_reward)
async def task_hours(message: Message, state: FSMContext) -> None:
    try:
        hours = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Вкажіть число.")
        return
    await state.update_data(hours_reward=hours)
    await state.set_state(AdminTaskState.deadline_day)
    await message.answer("📅 День дедлайну задачі (1–31) або слово <b>немає</b>, якщо дедлайн не потрібен.")


async def _finish_tg_task(message: Message, state: FSMContext, db: Database, deadline: datetime | None) -> None:
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            return
        balanced_xp = normalize_task_xp(data["xp_reward"], data["hours_reward"])
        task=VolunteerTask(title=data["title"], description=data["description"], xp_reward=balanced_xp, hours_reward=data["hours_reward"], deadline=deadline, created_by=admin.id)
        session.add(task); await session.flush()
        await _queue_new_entity_notice(session,f"✅ <b>Нова волонтерська задача</b>\n\n<b>{task.title}</b>\n⚡ {task.xp_reward} XP · ⏱ {task.hours_reward:g} год\n\nВідкрий «✅ Волонтерство» у боті, щоб долучитися.","task_created",f"task_created:{task.id}")
        await session.commit()
    await state.clear()
    text = "✅ Волонтерську задачу створено."
    if deadline:
        text += f"\n📅 Дедлайн: {deadline.strftime('%d.%m.%Y')} о {deadline.strftime('%H:%M')}"
    await message.answer(text)


@router.message(AdminTaskState.deadline_day)
async def task_deadline_day(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip().lower()
    if raw == "немає":
        await _finish_tg_task(message, state, db, None)
        return
    try:
        day = int(raw)
        if not 1 <= day <= 31:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть день числом від 1 до 31 або «немає».")
        return
    await state.update_data(deadline_day=day)
    await state.set_state(AdminTaskState.deadline_month)
    await message.answer("📅 Місяць дедлайну числом від 1 до 12.")


@router.message(AdminTaskState.deadline_month)
async def task_deadline_month(message: Message, state: FSMContext) -> None:
    try:
        month = int((message.text or "").strip())
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть місяць числом від 1 до 12.")
        return
    await state.update_data(deadline_month=month)
    await state.set_state(AdminTaskState.deadline_year)
    await message.answer("📅 Рік дедлайну, наприклад <b>2026</b>.")


@router.message(AdminTaskState.deadline_year)
async def task_deadline_year(message: Message, state: FSMContext) -> None:
    try:
        year = int((message.text or "").strip())
        if not 2026 <= year <= 2100:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть рік від 2026 до 2100.")
        return
    await state.update_data(deadline_year=year)
    await state.set_state(AdminTaskState.deadline_time)
    await message.answer("🕐 Час дедлайну у форматі <b>ГГ:ХХ</b>, наприклад 18:00.")


@router.message(AdminTaskState.deadline_time)
async def task_deadline_time(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "volunteer.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    try:
        hour, minute = [int(x) for x in raw.split(":", 1)]
        deadline = datetime(int(data["deadline_year"]), int(data["deadline_month"]), int(data["deadline_day"]), hour, minute)
    except Exception:
        await message.answer("Некоректна дата або час. Введіть час у форматі ГГ:ХХ, наприклад 18:00.")
        return
    await _finish_tg_task(message, state, db, deadline)


@router.callback_query(F.data == "admin:task_approvals")
async def task_approvals(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        rows = (await session.execute(
            select(VolunteerTaskParticipation, VolunteerTask, User)
            .join(VolunteerTask, VolunteerTask.id == VolunteerTaskParticipation.task_id)
            .join(User, User.id == VolunteerTaskParticipation.user_id)
            .where(VolunteerTaskParticipation.status == "submitted")
            .order_by(VolunteerTaskParticipation.submitted_at.asc())
        )).all()
        if not rows:
            await call.message.answer("✅ Немає волонтерських задач на підтвердження.")
        for part, task, user in rows[:30]:
            await call.message.answer(
                f"🧰 <b>{task.title}</b>\n👤 {user.full_name}\n⚡ {task.xp_reward} XP • ⏱ {task.hours_reward:g} год.",
                reply_markup=_single_button("✅ Підтвердити виконання", f"admin:approve_task_part:{part.id}"),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:approve_task_part:"))
async def approve_task_part(call: CallbackQuery, db: Database, bot: Bot) -> None:
    part_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        part = await session.get(VolunteerTaskParticipation, part_id)
        if not admin or not part or part.status != "submitted":
            await call.answer("Неактуально", show_alert=True)
            return
        task = await session.get(VolunteerTask, part.task_id)
        user = await session.get(User, part.user_id)
        if not task or not user:
            return
        task.xp_reward = normalize_task_xp(task.xp_reward, task.hours_reward)
        total, level, leveled = await add_xp(session, user, task.xp_reward, f"Волонтерська задача «{task.title}»", category="task", created_by=admin.id)
        user.volunteer_hours += task.hours_reward
        part.status = "approved"
        part.approved_at = datetime.utcnow()
        await evaluate_automatic_badges(session, user)
        text = f"✅ Задачу <b>{task.title}</b> підтверджено.\n+{task.xp_reward} XP\n+{task.hours_reward:g} год.\nВсього: {total} XP"
        if leveled:
            text += f"\n🎉 Новий рівень: <b>{level}</b>"
        await _queue_user_notice(session, user, text, source="xp_achievement", title="Волонтерську задачу підтверджено", entity_type="volunteer_task", entity_id=task.id, dedupe_key=f"task_approved:{task.id}:{user.id}")
        await session.commit()
        await call.answer("Підтверджено")


