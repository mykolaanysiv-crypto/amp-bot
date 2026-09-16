from ..time_utils import clock
from .participant_common import (
    Bot, CallbackQuery, Database, F, FSMContext, Idea, IdeaState, InlineKeyboardBuilder, Message, RequestCase, RequestMessage, RequestState, compact_button_text, escape, get_user_by_tg, label, log_extra, logging, request_status_label, router, save_telegram_photo, select
)

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
    except Exception as exc:
        logging.getLogger("amp.participant_requests").debug(
            "Не вдалося зафіксувати візуальний стан вибору категорії",
            exc_info=exc,
            extra=log_extra("TG_IDEA_CATEGORY_MARKUP_EDIT_FAILED", tg_id=call.from_user.id, category=value),
        )
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
            updated_at=clock.storage_utc(),
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
            updated_at=clock.storage_utc(),
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
        case.participant_last_viewed_at = clock.storage_utc()
        await session.commit()
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
        case.updated_at = clock.storage_utc()
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
        case.updated_at = clock.storage_utc()
        await session.commit()
    await state.clear()
    await message.answer("✅ Повідомлення додано до звернення.")


