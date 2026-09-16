from __future__ import annotations

from .common import (
    Bot, CallbackQuery, ConsentHistory, Database, F, FSMContext, MEDIA_CONSENT_VERSION, Message, PRIVACY_NOTICE_VERSION, RegistrationState, ReplyKeyboardRemove, Settings, SettlementReference, User, UserRole, UserStatus, VULNERABILITY_OPTIONS, _checkpoint, _gender_keyboard, _media_consent_keyboard, _normalize_phone, _privacy_keyboard, _safe_edit_reply_markup, _send_registration_prompt, _settlement_keyboard, _show_access, _valid_person_name, _vulnerability_keyboard, age_on, canonicalize_settlement_text, clock, create_referral_for_user, datetime, dump_vulnerabilities, ensure_user_tokens, get_registration_journey, get_user_by_tg, mark_registration_submitted, parse_vulnerability_numbers, queue_telegram_delivery, re, registration_progress, resolve_canonical_settlement, router, select, settlement_key, vulnerability_prompt
)

async def _accept_privacy(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.update_data(privacy_notice_version=PRIVACY_NOTICE_VERSION, privacy_acknowledged_at=clock.storage_utc().isoformat())
    await _checkpoint(state, db, settings, message.from_user.id, "last_name", mark_consent=True)
    await state.set_state(RegistrationState.last_name)
    await _send_registration_prompt(message, "last_name", db)

@router.callback_query(F.data.startswith("reg:privacy:"))
async def reg_privacy_callback(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    choice = call.data.rsplit(":", 1)[-1]
    if choice == "2":
        async with db.session_factory() as session:
            row = await get_registration_journey(session, call.from_user.id)
            if row:
                row.current_step = "declined"
                row.draft_ciphertext = ""
                row.updated_at = clock.storage_utc()
                await session.commit()
        await state.clear()
        await call.message.answer("Реєстрацію не продовжено. Ви можете повернутися пізніше командою /start.")
        await call.answer()
        return
    msg = call.message.model_copy(update={"from_user": call.from_user})
    await _accept_privacy(msg, state, db, settings)
    await _safe_edit_reply_markup(call, None, error_code="TG_REG_MARKUP_CLEAR_FAILED")
    await call.answer()

@router.message(RegistrationState.privacy_notice)
async def reg_privacy_notice(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    raw = (message.text or "").strip().lower()
    if raw in {"2", "ні", "no"}:
        async with db.session_factory() as session:
            row = await get_registration_journey(session, message.from_user.id)
            if row:
                row.current_step = "declined"; row.draft_ciphertext = ""; row.updated_at = clock.storage_utc()
                await session.commit()
        await state.clear()
        await message.answer("Реєстрацію не продовжено. Ви можете повернутися пізніше командою /start.")
        return
    if raw not in {"1", "так", "yes"}:
        await message.answer("Оберіть кнопку <b>«Продовжити»</b> або <b>«Не продовжувати»</b>.", reply_markup=_privacy_keyboard())
        return
    await _accept_privacy(message, state, db, settings)

@router.message(RegistrationState.last_name)
async def reg_last_name(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    value = (message.text or "").strip()
    if not _valid_person_name(value):
        await message.answer("❌ Не вдалося розпізнати прізвище. Напишіть щонайменше 2 літери, з великої літери, без цифр. Наприклад: <b>Прохоренко</b>.")
        return
    await state.update_data(last_name=value)
    await _checkpoint(state, db, settings, message.from_user.id, "first_name")
    await state.set_state(RegistrationState.first_name)
    await _send_registration_prompt(message, "first_name", db)

@router.message(RegistrationState.first_name)
async def reg_first_name(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    value = (message.text or "").strip()
    if not _valid_person_name(value):
        await message.answer("❌ Не вдалося розпізнати ім’я. Напишіть щонайменше 2 літери, з великої літери, без цифр. Наприклад: <b>Микола</b>.")
        return
    await state.update_data(first_name=value)
    await _checkpoint(state, db, settings, message.from_user.id, "phone")
    await state.set_state(RegistrationState.phone)
    await _send_registration_prompt(message, "phone", db)

async def _accept_phone(message: Message, state: FSMContext, db: Database, settings: Settings, phone: str) -> None:
    await state.update_data(phone=phone)
    await _checkpoint(state, db, settings, message.from_user.id, "email")
    await state.set_state(RegistrationState.email)
    await _send_registration_prompt(message, "email", db)

@router.message(RegistrationState.phone, F.contact)
async def reg_phone_contact(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer("❌ Надішліть, будь ласка, <b>власний</b> контакт або введіть свій номер вручну.")
        return
    phone = _normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("❌ Не вдалося прочитати номер. Введіть його вручну, наприклад <code>+380671234567</code>.")
        return
    await _accept_phone(message, state, db, settings, phone)

@router.message(RegistrationState.phone)
async def reg_phone_text(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    phone = _normalize_phone((message.text or "").strip())
    if not phone:
        await message.answer("❌ Номер має містити 10–15 цифр. Можна використовувати +, пробіли, дужки й дефіси. Приклад: <code>+380671234567</code>.")
        return
    await _accept_phone(message, state, db, settings, phone)

@router.message(RegistrationState.email)
async def reg_email(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    raw = (message.text or "").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
        await message.answer("❌ Це не схоже на email. Перевірте, чи є <b>@</b> і домен після крапки. Наприклад: <b>name@example.com</b>.")
        return
    await state.update_data(email=raw.lower())
    await _checkpoint(state, db, settings, message.from_user.id, "settlement")
    await state.set_state(RegistrationState.settlement)
    await _send_registration_prompt(message, "settlement", db)

async def _accept_settlement(message: Message, state: FSMContext, db: Database, settings: Settings, settlement: str) -> None:
    async with db.session_factory() as session:
        canonical = await resolve_canonical_settlement(session, settlement)
        await session.commit()
    if not canonical:
        await message.answer("❌ Не вдалося визначити населений пункт. Спробуйте ввести назву ще раз.")
        return
    await state.update_data(settlement=canonical)
    await _checkpoint(state, db, settings, message.from_user.id, "birth_date")
    await state.set_state(RegistrationState.birth_date)
    await _send_registration_prompt(message, "birth_date", db)

@router.callback_query(F.data.startswith("reg:settlement:"))
async def reg_settlement_callback(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    value = call.data.rsplit(":", 1)[-1]
    if value == "other":
        await call.message.answer(f"{registration_progress('settlement')}\n\n✍️ Почніть вводити назву населеного пункту. Я покажу найближчі збіги.")
        await call.answer(); return
    try: row_id = int(value)
    except ValueError:
        await call.answer("Некоректний вибір", show_alert=True); return
    async with db.session_factory() as session:
        row = await session.get(SettlementReference, row_id)
    if not row or not row.active:
        await call.answer("Цього варіанта вже немає у довіднику", show_alert=True); return
    msg = call.message.model_copy(update={"from_user": call.from_user})
    await _accept_settlement(msg, state, db, settings, row.canonical_name)
    await _safe_edit_reply_markup(call, None, error_code="TG_REG_MARKUP_CLEAR_FAILED")
    await call.answer()

@router.message(RegistrationState.settlement)
async def reg_settlement(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 2:
        await message.answer("❌ Введіть щонайменше 2 літери назви населеного пункту.")
        return
    async with db.session_factory() as session:
        rows = list((await session.scalars(select(SettlementReference).where(SettlementReference.active == True))).all())  # noqa: E712
        key = settlement_key(raw)
        exact = next((r for r in rows if settlement_key(r.canonical_name) == key), None)
        kb = await _settlement_keyboard(session, raw)
        candidates = sum(len(x) for x in kb.inline_keyboard)
    if exact:
        await _accept_settlement(message, state, db, settings, exact.canonical_name)
        return
    # Autocomplete instead of silently creating a typo as a new canonical place.
    if candidates:
        await message.answer("🔎 Знайшов схожі населені пункти. Оберіть потрібний. Якщо вашого немає — введіть повну назву ще раз.", reply_markup=kb)
        return
    # Unknown full values remain allowed, preserving legitimate locations outside the community.
    await _accept_settlement(message, state, db, settings, canonicalize_settlement_text(raw) or raw)

@router.message(RegistrationState.birth_date)
async def reg_birth_date(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    try:
        birth_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("❌ Не вдалося прочитати дату. Використайте формат <b>ДД.ММ.РРРР</b>, наприклад <b>17.04.2010</b>.")
        return
    today = clock.today_local()
    if birth_date > today:
        await message.answer("❌ Дата народження не може бути в майбутньому. Перевірте день, місяць і рік.")
        return
    if age_on(birth_date) > 120:
        await message.answer("❌ Рік виглядає некоректно. Перевірте дату та спробуйте ще раз.")
        return
    await state.update_data(birth_date=birth_date.isoformat())
    await _checkpoint(state, db, settings, message.from_user.id, "gender")
    await state.set_state(RegistrationState.gender)
    await _send_registration_prompt(message, "gender", db)

async def _accept_gender(message: Message, state: FSMContext, db: Database, settings: Settings, value: str) -> None:
    await state.update_data(gender=value)
    await _checkpoint(state, db, settings, message.from_user.id, "vulnerabilities")
    await state.set_state(RegistrationState.vulnerabilities)
    await _send_registration_prompt(message, "vulnerabilities", db)

@router.callback_query(F.data.startswith("reg:gender:"))
async def reg_gender_callback(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    value = call.data.rsplit(":", 1)[-1]
    if value not in {"female", "male", "other", "prefer_not_say"}:
        await call.answer("Некоректний вибір", show_alert=True); return
    msg = call.message.model_copy(update={"from_user": call.from_user})
    await _accept_gender(msg, state, db, settings, value)
    await _safe_edit_reply_markup(call, None, error_code="TG_REG_MARKUP_CLEAR_FAILED")
    await call.answer()

@router.message(RegistrationState.gender)
async def reg_gender(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    mapping = {"1": "female", "2": "male", "3": "other", "4": "prefer_not_say"}
    value = mapping.get((message.text or "").strip())
    if not value:
        await message.answer("Оберіть один із варіантів кнопками нижче.", reply_markup=_gender_keyboard())
        return
    await _accept_gender(message, state, db, settings, value)

@router.callback_query(F.data.startswith("reg:vuln:"))
async def reg_vulnerabilities_callback(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    action = call.data.rsplit(":", 1)[-1]
    data = await state.get_data()
    selected = list(data.get("vulnerability_codes") or [])
    by_number = {str(number): code for number, code, _ in VULNERABILITY_OPTIONS}
    if action == "private":
        selected = []
        await state.update_data(vulnerability_codes=selected, vulnerability_other="")
        msg = call.message.model_copy(update={"from_user": call.from_user})
        await _checkpoint(state, db, settings, call.from_user.id, "media_consent", mark_profile=True)
        await state.set_state(RegistrationState.media_consent)
        await _safe_edit_reply_markup(call, None, error_code="TG_REG_MARKUP_CLEAR_FAILED")
        await _send_registration_prompt(msg, "media_consent", db)
        await call.answer("Збережено без зазначення категорії")
        return
    if action == "done":
        if not selected:
            await call.answer("Оберіть хоча б один варіант або «Не бажаю зазначати».", show_alert=True)
            return
        needs_other = "other" in selected
        msg = call.message.model_copy(update={"from_user": call.from_user})
        await _safe_edit_reply_markup(call, None, error_code="TG_REG_MARKUP_CLEAR_FAILED")
        if needs_other:
            await _checkpoint(state, db, settings, call.from_user.id, "vulnerability_other")
            await state.set_state(RegistrationState.vulnerability_other)
            await _send_registration_prompt(msg, "vulnerability_other", db)
        else:
            await state.update_data(vulnerability_other="")
            await _checkpoint(state, db, settings, call.from_user.id, "media_consent", mark_profile=True)
            await state.set_state(RegistrationState.media_consent)
            await _send_registration_prompt(msg, "media_consent", db)
        await call.answer("Збережено")
        return
    code = by_number.get(action)
    if not code:
        await call.answer("Некоректний варіант", show_alert=True); return
    # «Не відношусь…» is exclusive; any other selection removes it.
    if code == "no_category":
        selected = [code]
    else:
        selected = [item for item in selected if item != "no_category"]
        if code in selected:
            selected.remove(code)
        else:
            selected.append(code)
    await state.update_data(vulnerability_codes=selected)
    await _checkpoint(state, db, settings, call.from_user.id, "vulnerabilities")
    await _safe_edit_reply_markup(call, _vulnerability_keyboard(selected), error_code="TG_REG_VULNERABILITY_MARKUP_EDIT_FAILED")
    await call.answer("Позначено" if code in selected else "Знято")

@router.message(RegistrationState.vulnerabilities)
async def reg_vulnerabilities(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    try:
        codes, needs_other = parse_vulnerability_numbers(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ Не вдалося зберегти відповідь: {exc}.\n\n{vulnerability_prompt()}")
        return
    await state.update_data(vulnerability_codes=codes)
    if needs_other:
        await _checkpoint(state, db, settings, message.from_user.id, "vulnerability_other")
        await state.set_state(RegistrationState.vulnerability_other)
        await _send_registration_prompt(message, "vulnerability_other", db)
        return
    await state.update_data(vulnerability_other="")
    await _checkpoint(state, db, settings, message.from_user.id, "media_consent", mark_profile=True)
    await state.set_state(RegistrationState.media_consent)
    await _send_registration_prompt(message, "media_consent", db)

@router.message(RegistrationState.vulnerability_other)
async def reg_vulnerability_other(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 2 or raw.lower() == "пропустити":
        await message.answer("❌ Для варіанта «Інша категорія» потрібно коротке уточнення — щонайменше 2 символи.")
        return
    await state.update_data(vulnerability_other=raw[:180])
    await _checkpoint(state, db, settings, message.from_user.id, "media_consent", mark_profile=True)
    await state.set_state(RegistrationState.media_consent)
    await _send_registration_prompt(message, "media_consent", db)

async def _accept_media_consent(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot, value: bool) -> None:
    await state.update_data(media_consent=value)
    await _checkpoint(state, db, settings, message.from_user.id, "media_consent")
    await _complete_registration(message, state, db, settings, bot)

@router.callback_query(F.data.startswith("reg:media:"))
async def reg_media_consent_callback(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    value = call.data.rsplit(":", 1)[-1]
    if value not in {"0", "1"}:
        await call.answer("Некоректний вибір", show_alert=True); return
    msg = call.message.model_copy(update={"from_user": call.from_user})
    await _accept_media_consent(msg, state, db, settings, bot, value == "1")
    await _safe_edit_reply_markup(call, None, error_code="TG_REG_MARKUP_CLEAR_FAILED")
    await call.answer()

@router.message(RegistrationState.media_consent)
async def reg_media_consent(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    raw = (message.text or "").strip().lower()
    mapping = {"1": True, "так": True, "yes": True, "2": False, "0": False, "ні": False, "no": False}
    if raw not in mapping:
        await message.answer("Оберіть <b>«Так»</b> або <b>«Ні»</b> кнопками нижче.", reply_markup=_media_consent_keyboard())
        return
    await _accept_media_consent(message, state, db, settings, bot, mapping[raw])

async def _complete_registration(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    data = await state.get_data()
    birth_date = datetime.fromisoformat(data["birth_date"]).date()
    minor = age_on(birth_date) < 18
    payload = data.get("start_payload") or ""
    referral_code = payload.removeprefix("ref_") if payload.startswith("ref_") else None
    last_name = (data.get("last_name") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    full_name = f"{last_name} {first_name}".strip()
    vulnerabilities = dump_vulnerabilities(data.get("vulnerability_codes") or [], data.get("vulnerability_other") or "")

    async with db.session_factory() as session:
        existing = await get_user_by_tg(session, message.from_user.id)
        if existing:
            await state.clear()
            await _show_access(message, existing, db)
            return
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=data.get("email"),
            phone=data.get("phone"),
            settlement=await resolve_canonical_settlement(session, data.get("settlement")),
            birth_date=birth_date,
            gender=data.get("gender"),
            vulnerability_categories=vulnerabilities,
            media_consent=data.get("media_consent"),
            media_consent_status="granted" if data.get("media_consent") is True else "declined",
            media_consent_version=MEDIA_CONSENT_VERSION,
            media_consent_recorded_at=clock.storage_utc(),
            privacy_notice_version=data.get("privacy_notice_version") or PRIVACY_NOTICE_VERSION,
            privacy_acknowledged_at=datetime.fromisoformat(data["privacy_acknowledged_at"]) if data.get("privacy_acknowledged_at") else clock.storage_utc(),
            role=UserRole.PARTICIPANT.value,
            status=UserStatus.PENDING.value,
            registration_review_status="pending",
            parental_consent_required=minor,
            parental_consent_confirmed=False,
            parental_consent_status="pending" if minor else "not_required",
            last_activity_at=clock.storage_utc(),
        )
        session.add(user)
        await session.flush()
        session.add(ConsentHistory(
            user_id=user.id,
            consent_type="media",
            status=user.media_consent_status,
            version=user.media_consent_version,
            changed_by_label="Telegram registration",
            changed_at=user.media_consent_recorded_at or clock.storage_utc(),
        ))
        if minor:
            session.add(ConsentHistory(
                user_id=user.id,
                consent_type="parental",
                status="pending",
                changed_by_label="Telegram registration",
            ))
        await ensure_user_tokens(session, user)
        await create_referral_for_user(session, user, referral_code)
        await mark_registration_submitted(session, message.from_user.id, user.id)
        await session.commit()

    await state.clear()
    msg = "✅ Анкету збережено. Адміністратор має підтвердити ваш профіль."
    if referral_code:
        msg += "\n🤝 Запрошення друга зафіксовано. Бонус запрошувачу буде нараховано після активації профілю."
    if payload.startswith("event_"):
        msg += "\n📅 Ви прийшли за посиланням на подію. Після активації профілю відкрийте це посилання ще раз — з’явиться кнопка реєстрації."
    if minor:
        msg += "\n👪 Оскільки вам ще немає 18 років, також потрібна згода батьків/законного представника."
    msg += "\n\n🔒 Чутливі дані з анкети призначені лише для внутрішньої роботи уповноваженої команди АМП."
    await message.answer(msg, reply_markup=ReplyKeyboardRemove())

    async with db.session_factory() as session:
        for admin_id in settings.superadmin_ids:
            if admin_id == message.from_user.id:
                continue
            admin_user = await session.scalar(select(User).where(User.tg_id == admin_id))
            await queue_telegram_delivery(
                session, admin_id,
                f"🆕 Нова реєстрація в АМП XP\n<b>{full_name}</b>\n"
                f"Населений пункт: {data.get('settlement') or '—'}\nНеповнолітній/ня: {'так' if minor else 'ні'}\n\n"
                "Відкрийте 🛠 Адмін-панель → 👥 Нові учасники.",
                source="registration", notification_type="system", title="Нова реєстрація",
                recipient_user_id=(admin_user.id if admin_user else None), entity_type="user", entity_id=user.id,
                dedupe_key=f"new_registration_staff:{user.id}:{admin_id}",
            )
        await session.commit()
