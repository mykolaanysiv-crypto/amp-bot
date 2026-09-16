from ..time_utils import clock
from .admin_common import (
    AdminEventScannerState, AdminEventState, Bot, BufferedInputFile, BytesIO, CallbackQuery, Database, Event, EventRegistration, F, FSMContext, InlineKeyboardBuilder, InlineKeyboardButton, InlineKeyboardMarkup, Message, Settings, User, WebAppInfo, _admin, _single_button, _two_buttons, _queue_new_entity_notice, _queue_user_notice, _require_admin, _require_permission, admin_scan_event_participant, compact_button_text, confirm_event_attendance, create_event, datetime, event_checkin_window, func, log_audit, log_extra, logging, normalize_event_xp, parse_qs, qrcode, queue_telegram_delivery, quote, re, router, select, timedelta, urlparse
)

@router.callback_query(F.data == "admin:create_event")
async def create_event_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminEventState.title)
    await call.message.answer("📅 Назва події?")
    await call.answer()


@router.message(AdminEventState.title)
async def event_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminEventState.description)
    await message.answer("Короткий опис події?")


@router.message(AdminEventState.description)
async def event_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminEventState.day)
    await message.answer("📅 Вкажіть <b>число місяця</b> (1–31).")


@router.message(AdminEventState.day)
async def event_day(message: Message, state: FSMContext) -> None:
    try: day = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть число від 1 до 31."); return
    if not 1 <= day <= 31:
        await message.answer("Вкажіть число від 1 до 31."); return
    await state.update_data(day=day)
    await state.set_state(AdminEventState.month)
    await message.answer("📅 Вкажіть <b>номер місяця</b> (1–12). Наприклад: 9 — вересень.")


@router.message(AdminEventState.month)
async def event_month(message: Message, state: FSMContext) -> None:
    try: month = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть номер місяця від 1 до 12."); return
    if not 1 <= month <= 12:
        await message.answer("Вкажіть номер місяця від 1 до 12."); return
    await state.update_data(month=month)
    await state.set_state(AdminEventState.year)
    await message.answer("📅 Вкажіть <b>рік</b>, наприклад 2026.")


@router.message(AdminEventState.year)
async def event_year(message: Message, state: FSMContext) -> None:
    try: year = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть рік числом."); return
    if not 2026 <= year <= 2100:
        await message.answer("Вкажіть рік у межах 2026–2100."); return
    await state.update_data(year=year)
    await state.set_state(AdminEventState.event_time)
    await message.answer("🕒 Вкажіть <b>час</b> у форматі ГГ:ХХ, наприклад 18:30.")


@router.message(AdminEventState.event_time)
async def event_date(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        hour, minute = [int(x) for x in raw.split(":", 1)]
        if not (0 <= hour <= 23 and 0 <= minute <= 59): raise ValueError
    except Exception:
        await message.answer("Формат часу: 18:30")
        return
    data = await state.get_data()
    try:
        dt = datetime(int(data["year"]), int(data["month"]), int(data["day"]), hour, minute)
    except ValueError:
        await message.answer("Такої календарної дати не існує. Почніть створення події ще раз.")
        await state.clear()
        return
    await state.update_data(starts_at=dt.isoformat())
    await state.set_state(AdminEventState.location)
    await message.answer("📍 Локація? Наприклад: АМП / парк с. Анисів / онлайн.")


@router.message(AdminEventState.location)
async def event_location(message: Message, state: FSMContext) -> None:
    await state.update_data(location=(message.text or "").strip())
    await state.set_state(AdminEventState.xp_reward)
    await message.answer("⚡ Скільки XP отримає підтверджений учасник? Допустимо 5–25 XP, типовий захід — 10 XP.")


@router.message(AdminEventState.xp_reward)
async def event_xp(message: Message, state: FSMContext) -> None:
    try:
        xp = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число.")
        return
    xp = normalize_event_xp(xp)
    await state.update_data(xp_reward=xp)
    await state.set_state(AdminEventState.volunteer_hours)
    await message.answer("⏱ Скільки волонтерських годин зарахувати? Наприклад 2 або 0.")


@router.message(AdminEventState.volunteer_hours)
async def event_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "events.create"):
        await state.clear()
        return
    try:
        hours = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Вкажіть число, наприклад 2 або 1.5.")
        return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            await state.clear()
            return
        event = await create_event(
            session,
            data["title"], data["description"], datetime.fromisoformat(data["starts_at"]),
            data["location"], data["xp_reward"], hours, admin.id,
        )
        await _queue_new_entity_notice(session,f"📅 <b>Нова подія в АМП</b>\n\n<b>{event.title}</b>\n🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n📍 {event.location}\n⚡ {event.xp_reward} XP\n\nВідкрий «📅 Події» у боті, щоб зареєструватися.","event_created",f"event_created:{event.id}")
        await session.commit()
        username = (await bot.get_me()).username
        deep_link = f"https://t.me/{username}?start=checkin_{event.checkin_token}"
        img = qrcode.make(deep_link)
        bio = BytesIO()
        img.save(bio, format="PNG")
        await message.answer_photo(
            BufferedInputFile(bio.getvalue(), filename=f"event_{event.id}_qr.png"),
            caption=(
                f"✅ Подію <b>{event.title}</b> створено.\n"
                f"Номер: {event.id}\n⚡ {event.xp_reward} XP • ⏱ {hours:g} год.\n\n"
                "QR-код використовується для відмітки присутності. XP нарахуються лише після підтвердження адміністратором."
            ),
        )
    await state.clear()


def _event_select_markup(events, callback_prefix: str):
    b = InlineKeyboardBuilder()
    for event in events:
        title = compact_button_text(f"{event.title} · {event.starts_at.strftime('%d.%m %H:%M')}", 42)
        b.button(text=title, callback_data=f"{callback_prefix}:{event.id}")
    b.adjust(1)
    return b.as_markup()


def _scanner_participant_identity(raw: str) -> tuple[int | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    amp = re.fullmatch(r"(?:AMP|АМП)-?(\d{1,9})", text, flags=re.I)
    if amp:
        return int(amp.group(1)), None
    if text.isdigit():
        return int(text), None
    if text.startswith("profile_"):
        return None, text.removeprefix("profile_")
    try:
        parsed = urlparse(text)
        payload = (parse_qs(parsed.query).get("start") or [""])[0]
        if payload.startswith("profile_"):
            return None, payload.removeprefix("profile_")
    except (TypeError, ValueError) as exc:
        logging.getLogger("amp.admin_events").debug(
            "Не вдалося розібрати scanner URL",
            extra=log_extra("ADMIN_SCANNER_URL_PARSE_FAILED", input_length=len(text), exception_type=type(exc).__name__),
        )
    match = re.search(r"(?:start=|/)profile_([A-Za-z0-9_-]{8,80})", text)
    return (None, match.group(1)) if match else (None, None)


def _scanner_controls():
    b = InlineKeyboardBuilder()
    b.button(text="⛔ Завершити сканування", callback_data="admin:event_scanner_stop")
    return b.as_markup()


async def _telegram_scanner_result(message: Message, state: FSMContext, db: Database, admin: User, event_id: int, participant_id: int, *, allow_register: bool = False) -> None:
    async with db.session_factory() as session:
        admin_db = await session.get(User, admin.id)
        result = await admin_scan_event_participant(session, event_id, participant_id, admin_db, allow_register=allow_register)
        event = result.get("event")
        user = result.get("user")
        code = result.get("code")
        if code == "unregistered" and user and event:
            b = InlineKeyboardBuilder()
            b.button(text="✅ Зареєструвати та підтвердити", callback_data=f"admin:event_scanner_confirm:{event.id}:{user.id}")
            b.button(text="⛔ Завершити", callback_data="admin:event_scanner_stop")
            b.adjust(1)
            await message.answer(
                f"⚠️ <b>{user.full_name}</b>\n"
                f"🪪 АМП-{user.id:04d}\n\n"
                f"Учасник не зареєстрований на подію «{event.title}».",
                reply_markup=b.as_markup(),
            )
            return
        if not result.get("ok"):
            await message.answer(f"❌ {result.get('message', 'Не вдалося обробити QR.')}", reply_markup=_scanner_controls())
            return
        if code == "already_attended" and user and event:
            await message.answer(
                f"ℹ️ <b>{user.full_name}</b>\n"
                f"🪪 АМП-{user.id:04d}\n"
                f"✅ Участь у «{event.title}» уже підтверджена.\n\n"
                "Скануйте наступний QR.",
                reply_markup=_scanner_controls(),
            )
            return
        if code == "confirmed" and user and event:
            await log_audit(session, "telegram_event_qr_scanner_attendance", admin_db, entity_type="event", entity_id=event.id, details=f"АМП-{user.id:04d}")
            notice = f"✅ Участь у події «{event.title}» підтверджено.\n+{event.xp_reward} XP"
            if event.volunteer_hours:
                notice += f"\n+{event.volunteer_hours:g} волонтерських годин"
            notice += f"\nВсього: {result.get('total_xp', 0)} XP"
            await queue_telegram_delivery(session, user.tg_id, notice, source="telegram_event_scanner", dedupe_key=f"telegram_event_scanner:{event.id}:{result['registration'].id}")
            await session.commit()
            await message.answer(
                f"✅ <b>{user.full_name}</b>\n"
                f"🪪 АМП-{user.id:04d}\n"
                f"📅 {event.title}\n\n"
                f"<b>Присутність підтверджено</b> • +{event.xp_reward} XP\n\n"
                "Скануйте наступний QR.",
                reply_markup=_scanner_controls(),
            )


@router.callback_query(F.data == "admin:event_scanner")
async def admin_event_scanner_list(call: CallbackQuery, db: Database, settings: Settings) -> None:
    """Launch the Telegram Mini App scanner directly from the selected event.

    The event button itself is a Web App button.  One tap therefore opens the
    Telegram-native QR camera; there is no browser QR API dependency.
    """
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав", show_alert=True); return
        events = list((await session.scalars(
            select(Event).where(
                Event.status.in_(["open", "closed", "postponed"]),
                Event.starts_at >= clock.local_wall(clock.now_utc() - timedelta(hours=12)),
            ).order_by(Event.starts_at.asc()).limit(25)
        )).all())
    if not events:
        await call.message.answer("📷 Немає активних подій для QR-сканера.")
        await call.answer(); return

    base = (settings.public_base_url or "").rstrip("/")
    if not base.startswith("https://"):
        await call.message.answer(
            "⚠️ Для QR-сканера в Telegram потрібна HTTPS-адреса PUBLIC_BASE_URL. "
            "У production Heroku він має починатися з https://."
        )
        await call.answer(); return
    rows = []
    for event in events:
        title = compact_button_text(f"📷 {event.title} · {event.starts_at.strftime('%d.%m %H:%M')}", 48)
        rows.append([InlineKeyboardButton(
            text=title,
            web_app=WebAppInfo(url=f"{base}/tg/event-scanner/{event.id}"),
        )])
    rows.append([InlineKeyboardButton(text="📝 Текстовий режим", callback_data="admin:event_scanner_textmode")])
    await call.message.answer(
        "📷 <b>QR-сканер у Telegram</b>\n\n"
        "Оберіть подію — Telegram одразу відкриє сканер QR. Камера залишатиметься відкритою після кожного бейджа, щоб можна було сканувати учасників один за одним.\n\n"
        "Після кожного сканування бот надішле в чат результат: ПІБ, АМП-код, назву події та статус реєстрації/присутності.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@router.callback_query(F.data == "admin:event_scanner_textmode")
async def admin_event_scanner_textmode(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав", show_alert=True); return
        events = list((await session.scalars(
            select(Event).where(
                Event.status.in_(["open", "closed", "postponed"]),
                Event.starts_at >= clock.local_wall(clock.now_utc() - timedelta(hours=12)),
            ).order_by(Event.starts_at.asc()).limit(25)
        )).all())
    if events:
        await call.message.answer(
            "📝 Оберіть подію для резервного текстового режиму. Після цього можна надсилати АМП-код або текст QR.",
            reply_markup=_event_select_markup(events, "admin:event_scanner_select"),
        )
    await call.answer()


@router.callback_query(F.data.startswith("admin:event_scanner_select:"))
async def admin_event_scanner_select(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    event_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not admin or not event or event.status not in {"open", "closed", "postponed"}:
            await call.answer("Подія недоступна", show_alert=True); return
    await state.set_state(AdminEventScannerState.scanning)
    await state.update_data(event_scanner_event_id=event_id)
    await call.message.answer(
        f"📷 <b>QR-сканер активний</b>\n"
        f"📅 {event.title}\n\n"
        "1. Відкрийте камеру телефона.\n"
        "2. Наведіть її на персональний QR-бейдж учасника.\n"
        "3. Відкрийте посилання Telegram із QR.\n"
        "4. Бот підтвердить участь і залишиться в режимі сканування.\n\n"
        "Альтернатива: надішліть сюди <code>АМП-0008</code> або текст/посилання з QR.\n\n"
        "ℹ️ Режим Telegram не залежить від browser QR API, тому працює незалежно від Chrome/Safari/Firefox/Edge.",
        reply_markup=_scanner_controls(),
    )
    await call.answer("QR-сканер увімкнено")


@router.message(AdminEventScannerState.scanning)
async def admin_event_scanner_text(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "events.edit"):
        await state.clear()
        return
    data = await state.get_data()
    event_id = int(data.get("event_scanner_event_id") or 0)
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin or not event_id:
            await state.clear(); return
        participant_id, token = _scanner_participant_identity(message.text or "")
        if token:
            target = await session.scalar(select(User).where(User.public_token == token))
            participant_id = target.id if target else None
    if not participant_id:
        await message.answer("⚠️ Не вдалося розпізнати учасника. Скануйте персональний QR-бейдж або надішліть АМП-код, наприклад <code>АМП-0008</code>.", reply_markup=_scanner_controls())
        return
    await _telegram_scanner_result(message, state, db, admin, event_id, participant_id)


@router.callback_query(F.data.startswith("admin:event_scanner_confirm:"))
async def admin_event_scanner_register_confirm(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    try:
        _, _, event_id_raw, user_id_raw = call.data.split(":")
        event_id, user_id = int(event_id_raw), int(user_id_raw)
    except Exception:
        await call.answer("Некоректні дані", show_alert=True); return
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
    if not admin:
        await call.answer("Недостатньо прав", show_alert=True); return
    await _telegram_scanner_result(call.message, state, db, admin, event_id, user_id, allow_register=True)
    await call.answer("Участь підтверджено")


@router.callback_query(F.data == "admin:event_scanner_stop")
async def admin_event_scanner_stop(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer("✅ QR-сканування завершено.")
    await call.answer()


@router.callback_query(F.data == "admin:event_qr")
async def admin_event_qr_list(call: CallbackQuery, db: Database) -> None:
    """Coordinator/admin/superadmin: choose an active event and download its check-in QR."""
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав", show_alert=True); return
        events = list((await session.scalars(
            select(Event).where(
                Event.status.in_(["open", "closed", "postponed"]),
                Event.starts_at >= clock.local_wall(clock.now_utc() - timedelta(hours=12)),
            ).order_by(Event.starts_at.asc()).limit(25)
        )).all())
    if not events:
        await call.message.answer("🔳 Немає активних подій, для яких можна згенерувати QR відмітки.")
        await call.answer(); return
    await call.message.answer(
        "🔳 <b>QR для відмітки участі</b>\n\nОберіть активну подію. Після вибору бот надішле PNG-файл, який можна завантажити, роздрукувати або показати на екрані.",
        reply_markup=_event_select_markup(events, "admin:event_qr_make"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:event_qr_make:"))
async def admin_event_qr_make(call: CallbackQuery, db: Database, bot: Bot) -> None:
    event_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not admin or not event or event.status not in {"open", "closed", "postponed"}:
            await call.answer("Подія недоступна", show_alert=True); return
        await log_audit(session, "telegram_event_qr_generated", admin, entity_type="event", entity_id=event.id, details=event.title)
        await session.commit()
    username = (await bot.get_me()).username
    deep_link = f"https://t.me/{username}?start=checkin_{event.checkin_token}"
    qr = qrcode.QRCode(version=None, box_size=12, border=3)
    qr.add_data(deep_link); qr.make(fit=True)
    image = qr.make_image(fill_color="#0B5B6C", back_color="white").convert("RGB")
    bio = BytesIO(); image.save(bio, format="PNG")
    await call.message.answer_document(
        BufferedInputFile(bio.getvalue(), filename=f"AMP_event_{event.id}_checkin_QR.png"),
        caption=(f"🔳 <b>QR відмітки для події</b>\n<b>{event.title}</b>\n🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                 "Учасник сканує QR → Telegram фіксує check-in → адміністратор/координатор підтверджує участь. XP і години нараховуються лише після підтвердження."),
    )
    await call.answer("QR згенеровано")


@router.callback_query(F.data == "admin:event_share_link")
async def admin_event_share_list(call: CallbackQuery, db: Database) -> None:
    """Admin/superadmin: generate a public registration/share link from Telegram."""
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав для цієї дії", show_alert=True); return
        events = list((await session.scalars(
            select(Event).where(
                Event.status.in_(["open", "postponed"]),
                Event.starts_at >= clock.local_wall(),
            ).order_by(Event.starts_at.asc()).limit(25)
        )).all())
    if not events:
        await call.message.answer("🔗 Немає майбутніх подій із відкритою реєстрацією.")
        await call.answer(); return
    await call.message.answer("🔗 <b>Посилання для реєстрації на подію</b>\n\nОберіть подію:", reply_markup=_event_select_markup(events, "admin:event_share_make"))
    await call.answer()


@router.callback_query(F.data.startswith("admin:event_share_make:"))
async def admin_event_share_make(call: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    event_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not admin or not event or not event.share_token:
            await call.answer("Подію або посилання не знайдено", show_alert=True); return
        await log_audit(session, "telegram_event_share_link_generated", admin, entity_type="event", entity_id=event.id, details=event.title)
        await session.commit()
    public_url = f"{settings.public_base_url}/event/{event.share_token}"
    username = (await bot.get_me()).username
    registration_url = f"https://t.me/{username}?start=event_{event.share_token}"
    share_url = "https://t.me/share/url?url=" + quote(public_url, safe="") + "&text=" + quote(f"Подія АМП: {event.title}", safe="")
    b = InlineKeyboardBuilder()
    b.button(text="📤 Переслати другу", url=share_url)
    b.button(text="🙋 Пряма реєстрація в Telegram", url=registration_url)
    b.button(text="🌐 Відкрити сторінку", url=public_url)
    b.adjust(1)
    await call.message.answer(
        f"🔗 <b>{event.title}</b>\n\n"
        f"🌐 Публічна сторінка події:\n<code>{public_url}</code>\n\n"
        f"🙋 Пряме посилання для реєстрації в Telegram:\n<code>{registration_url}</code>\n\n"
        "Посилання реєстрації використовує окремий share-token і не розкриває QR/check-in код події.",
        reply_markup=b.as_markup(),
    )
    await call.answer("Посилання готове")


@router.callback_query(F.data == "admin:attendance")
async def attendance_events(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        events = (await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(15))).all()
        if not events:
            await call.message.answer("Подій немає.")
            return
        for e in events:
            pending = await session.scalar(
                select(func.count(EventRegistration.id)).where(EventRegistration.event_id == e.id, EventRegistration.status == "checked_in")
            )
            await call.message.answer(
                f"📅 <b>{e.title}</b> • {e.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"Очікує підтвердження: <b>{pending or 0}</b>",
                reply_markup=None if not pending else _single_button("✅ Підтвердити всіх присутніх", f"admin:confirm_event:{e.id}"),
            )
        await call.answer()



@router.callback_query(F.data.startswith("admin:confirm_event:"))
async def confirm_attendance(call: CallbackQuery, db: Database, bot: Bot) -> None:
    event_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not admin or not event:
            await call.answer("Не знайдено", show_alert=True)
            return
        window = await event_checkin_window(session, event)
        if window["state"] != "open":
            when = window["opens_at"] if window["state"] == "too_early" else window["closes_at"]
            hint = (
                f"Відмітка відкриється {when.strftime('%d.%m.%Y %H:%M')}."
                if window["state"] == "too_early"
                else f"Вікно attendance закрилося {when.strftime('%d.%m.%Y %H:%M')}."
            )
            await call.message.answer(
                "⛔ Звичайне підтвердження участі зараз недоступне.\n" + hint +
                "\nДля винятку використайте web-панель: ручний override потребує причини й записується в аудит."
            )
            await call.answer("Поза вікном відмітки", show_alert=True)
            return
        count, results = await confirm_event_attendance(session, event, admin)
        for user, total, level, leveled in results:
            text = f"✅ Участь у <b>{event.title}</b> підтверджено.\n+{event.xp_reward} XP"
            if event.volunteer_hours:
                text += f"\n+{event.volunteer_hours:g} волонтерських годин"
            text += f"\nВсього: {total} XP"
            if leveled:
                text += f"\n🎉 Новий рівень: <b>{level}</b>"
            await _queue_user_notice(session, user, text, source="event_attendance", entity_type="event", entity_id=event.id, dedupe_key=f"tg_event_attendance:{event.id}:{user.id}")
        await session.commit()
        await call.message.answer(f"✅ Підтверджено учасників: <b>{count}</b>.")
        await call.answer()


