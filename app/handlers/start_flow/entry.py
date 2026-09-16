from __future__ import annotations

from .common import (
    AdminEventScannerState, Bot, CallbackQuery, Command, CommandObject, CommandStart, Database, Event, EventRegistration, F, FSMContext, InlineKeyboardButton, InlineKeyboardMarkup, Message, REGISTRATION_STATE_BY_STEP, RegistrationState, RestorationState, Settings, User, UserRole, UserStatus, WebAppInfo, _resume_keyboard, _send_registration_prompt, _show_access, admin_scan_event_participant, checkin_for_event, clock, decrypt_draft, ensure_user_tokens, escape, event_checkin_window, event_detail_keyboard, get_registration_journey, get_user_by_tg, json, lifecycle_status_label, log_audit, queue_telegram_delivery, quote, registration_progress, restart_registration_journey, router, season_xp, select, xp_total
)

@router.message(CommandStart())
async def start(message: Message, state: FSMContext, command: CommandObject, db: Database, settings: Settings, bot: Bot) -> None:
    payload = command.args or ""
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)

        # Scanner deep-link from the web admin panel. Telegram cannot open a
        # Mini App without a user gesture, so the deep-link presents a single
        # Web App button; once tapped, the Mini App opens the native QR camera
        # automatically and keeps it open for continuous badge scanning.
        if payload.startswith("adminscan_") and user and user.status == UserStatus.ACTIVE.value and user.role in {UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
            token = payload.removeprefix("adminscan_")
            event = await session.scalar(select(Event).where(Event.checkin_token == token))
            if event and event.status in {"open", "closed", "postponed"}:
                base = (settings.public_base_url or "").rstrip("/")
                buttons = []
                if base.startswith("https://"):
                    buttons.append([InlineKeyboardButton(
                        text="📷 Відкрити камеру QR-сканера",
                        web_app=WebAppInfo(url=f"{base}/tg/event-scanner/{event.id}"),
                    )])
                buttons.append([InlineKeyboardButton(text="📝 Текстовий режим", callback_data=f"admin:event_scanner_select:{event.id}")])
                await message.answer(
                    f"📷 <b>QR-сканер</b>\n📅 {event.title}\n\n"
                    "Натисніть «Відкрити камеру QR-сканера». Камера відкриється всередині Telegram і залишатиметься активною після кожного сканування.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                )
                return

        if payload.startswith("profile_"):
            token = payload.removeprefix("profile_")
            target = await session.scalar(select(User).where(User.public_token == token, User.status == UserStatus.ACTIVE.value))
            scanner_state = await state.get_state()
            scanner_data = await state.get_data() if scanner_state == AdminEventScannerState.scanning.state else {}
            scanner_event_id = int(scanner_data.get("event_scanner_event_id") or 0)
            if target and user and scanner_event_id and user.status == UserStatus.ACTIVE.value and user.role in {UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
                result = await admin_scan_event_participant(session, scanner_event_id, target.id, user, allow_register=False)
                event = result.get("event")
                if result.get("code") == "unregistered" and event:
                    await message.answer(
                        f"⚠️ <b>{target.full_name}</b>\n🪪 АМП-{target.id:04d}\n\nУчасник не зареєстрований на подію «{event.title}».",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Зареєструвати та підтвердити", callback_data=f"admin:event_scanner_confirm:{event.id}:{target.id}")],[InlineKeyboardButton(text="⛔ Завершити сканування", callback_data="admin:event_scanner_stop")]]),
                    )
                    return
                if result.get("code") == "already_attended" and event:
                    await message.answer(f"ℹ️ <b>{target.full_name}</b> • АМП-{target.id:04d}\n✅ Участь у «{event.title}» уже підтверджена.\n\nСкануйте наступний QR.")
                    return
                if result.get("ok") and result.get("code") == "confirmed" and event:
                    await log_audit(session, "telegram_event_qr_scanner_attendance", user, entity_type="event", entity_id=event.id, details=f"АМП-{target.id:04d}")
                    await queue_telegram_delivery(session, target.tg_id, f"✅ Участь у події «{event.title}» підтверджено.\n+{event.xp_reward} XP", source="telegram_event_scanner", dedupe_key=f"telegram_event_scanner:{event.id}:{result['registration'].id}")
                    await session.commit()
                    await message.answer(f"✅ <b>{target.full_name}</b>\n🪪 АМП-{target.id:04d}\n📅 {event.title}\n\n<b>Присутність підтверджено</b> • +{event.xp_reward} XP\n\nСкануйте наступний QR.")
                    return
                await message.answer(f"❌ {result.get('message', 'Не вдалося обробити QR.')}")
                return

            # Public personal badge can still be opened without registration or
            # outside scanner mode.
            if target:
                total = await xp_total(session, target.id)
                sxp = await season_xp(session, target.id)
                from ...gamification import get_level
                level = get_level(total)[0]
                await message.answer(
                    f"🚀 <b>АМПасадор • публічна картка</b>\n\n"
                    f"👤 <b>{target.full_name}</b>\n"
                    f"🪪 АМП-{target.id:04d}\n"
                    f"🏅 {level}\n"
                    f"⚡ Загальний XP: <b>{total}</b>\n"
                    f"📈 XP сезону: <b>{sxp}</b>\n"
                    f"⏱ Волонтерських годин: <b>{target.volunteer_hours:g}</b>"
                )
                return
        if not user and message.from_user.id in settings.superadmin_ids:
            user = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                role=UserRole.SUPERADMIN.value,
                status=UserStatus.ACTIVE.value,
                last_activity_at=clock.storage_utc(),
            )
            session.add(user)
            await session.flush()
            await ensure_user_tokens(session, user)
            await session.commit()
            await _show_access(message, user, db)
            return

        if not user:
            # v1.11.0: registration checkpoints survive /menu, /start and dyno restarts.
            journey = await get_registration_journey(session, message.from_user.id)
            resumable = bool(journey and journey.current_step in REGISTRATION_STATE_BY_STEP)
            if resumable:
                await state.clear()
                if payload and not journey.start_payload:
                    journey.start_payload = payload[:180]
                    journey.updated_at = clock.storage_utc()
                    await session.commit()
                await message.answer(
                    "👋 <b>Реєстрацію ще не завершено.</b>\n\n"
                    f"{registration_progress(journey.current_step)}\n"
                    "Можна продовжити з місця, де ви зупинилися, або почати анкету спочатку.",
                    reply_markup=_resume_keyboard(),
                )
                return
            await state.clear()
            journey = await restart_registration_journey(session, message.from_user.id, start_payload=payload)
            await session.commit()
            await state.set_state(RegistrationState.privacy_notice)
            if payload:
                await state.update_data(start_payload=payload)
            await message.answer("👋 Вітаємо в <b>АМПасадори / АМП XP</b>!")
            await _send_registration_prompt(message, "privacy_notice", db)
            return

        await ensure_user_tokens(session, user)
        user.username = message.from_user.username
        if user.role == UserRole.SUPERADMIN.value and (user.full_name.startswith("Superadmin ") or user.full_name.startswith("Суперадміністратор ")):
            user.full_name = message.from_user.full_name
        await session.commit()

        if payload.startswith("event_"):
            share_token = payload.removeprefix("event_")
            event = await session.scalar(select(Event).where(Event.share_token == share_token))
            if event and event.status != "draft":
                if user.status != UserStatus.ACTIVE.value:
                    await message.answer("ℹ️ Це посилання на подію. Після активації профілю відкрийте його ще раз, щоб зареєструватися.")
                    await _show_access(message, user, db)
                    return
                reg = await session.scalar(select(EventRegistration).where(EventRegistration.event_id == event.id, EventRegistration.user_id == user.id))
                registered = bool(reg and reg.status != "cancelled")
                public_url = f"{settings.public_base_url}/event/{event.share_token}"
                share_button_url = "https://t.me/share/url?url=" + quote(public_url, safe="") + "&text=" + quote(f"Подія АМП: {event.title}", safe="")
                keyboard = None
                if event.status in {"open", "postponed"} and clock.event_utc(event.starts_at) >= clock.now_utc():
                    keyboard = event_detail_keyboard(event.id, registered, share_button_url, reg.status if reg else None)
                elif event.status == "closed" and registered:
                    keyboard = event_detail_keyboard(event.id, True, share_button_url, reg.status if reg else None)
                text = (
                    f"📅 <b>{escape(event.title)}</b>\n"
                    f"🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📍 {escape(event.location or 'АМП')}\n"
                    f"📌 Статус: {lifecycle_status_label(event.status)}\n"
                    f"⚡ {event.xp_reward} XP\n"
                    f"⏱ {event.volunteer_hours:g} волонтерських годин\n\n"
                    f"{escape(event.description or '')}"
                )
                await message.answer(text, reply_markup=keyboard)
                return
            await message.answer("❌ Посилання на подію недійсне або подія більше недоступна.")
            await _show_access(message, user, db)
            return

        if payload.startswith("checkin_") and user.status == UserStatus.ACTIVE.value:
            token = payload.removeprefix("checkin_")
            event, status = await checkin_for_event(session, user.id, token)
            if status == "ok" and event:
                await session.commit()
                await message.answer(f"✅ Відмітку присутності зафіксовано на події <b>{event.title}</b>.\nXP буде нараховано після підтвердження координатором.")
            elif status in {"too_early", "window_closed"} and event:
                window = await event_checkin_window(session, event)
                if status == "too_early":
                    await message.answer(
                        f"⏳ Відмітка на подію <b>{event.title}</b> ще не відкрито.\n"
                        f"Відкриється: <b>{window['opens_at'].strftime('%d.%m.%Y %H:%M')}</b>."
                    )
                else:
                    await message.answer(
                        f"⌛ Вікно check-in на подію <b>{event.title}</b> уже завершено.\n"
                        "Якщо це помилка, зверніться до координатора АМП."
                    )
            else:
                await message.answer("❌ QR події недійсний або застарілий.")

        await _show_access(message, user, db)

@router.callback_query(F.data == "restore:start")
async def restoration_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, callback.from_user.id)
        if not user or user.status != UserStatus.DELETED.value:
            await callback.answer("Відновлення для цього профілю недоступне.", show_alert=True)
            return
        if user.restoration_request_status == "pending":
            await callback.answer("Запит уже очікує розгляду.", show_alert=True)
            return
    await state.clear()
    await state.set_state(RestorationState.reason)
    await callback.message.answer(
        "♻️ <b>Відновлення акаунта</b>\n\n1/3. Коротко напишіть, чому хочете повернутися до АМПасадорів."
    )
    await callback.answer()

@router.message(RestorationState.reason)
async def restoration_reason(message: Message, state: FSMContext) -> None:
    text=(message.text or "").strip()
    if len(text) < 3:
        await message.answer("Напишіть, будь ласка, коротку відповідь.")
        return
    await state.update_data(reason=text[:1000])
    await state.set_state(RestorationState.future_activity)
    await message.answer("2/3. У яких активностях АМП ви плануєте брати участь після відновлення?")

@router.message(RestorationState.future_activity)
async def restoration_future(message: Message, state: FSMContext) -> None:
    text=(message.text or "").strip()
    if len(text) < 3:
        await message.answer("Напишіть, будь ласка, коротку відповідь.")
        return
    await state.update_data(future_activity=text[:1000])
    await state.set_state(RestorationState.confirmation)
    await message.answer(
        "3/3. Після відновлення діятиме <b>14-денний випробувальний строк</b>. "
        "Якщо за цей час не буде жодної підтвердженої участі в активностях АМП, акаунт буде видалено без можливості повторного відновлення.\n\n"
        "Надішліть <b>ТАК</b>, якщо погоджуєтесь."
    )

@router.message(RestorationState.confirmation)
async def restoration_confirm(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if (message.text or "").strip().upper() not in {"ТАК", "YES", "1"}:
        await message.answer("Для підтвердження надішліть <b>ТАК</b> або /cancel.")
        return
    data=await state.get_data()
    async with db.session_factory() as session:
        user=await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.DELETED.value:
            await state.clear(); await message.answer("Відновлення більше недоступне."); return
        user.restoration_requested_at=clock.storage_utc()
        user.restoration_request_status="pending"
        user.restoration_answers_json=json.dumps({"reason":data.get("reason",""),"future_activity":data.get("future_activity","")},ensure_ascii=False)
        await session.commit()
        uid=user.id; name=user.full_name
    await state.clear()
    await message.answer("✅ Запит на відновлення надіслано. Суперадміністратор розгляне його найближчим часом.")
    async with db.session_factory() as session:
        for admin_id in settings.superadmin_ids:
            admin_user = await session.scalar(select(User).where(User.tg_id == admin_id))
            await queue_telegram_delivery(
                session, admin_id,
                f"♻️ <b>Новий запит на відновлення акаунта</b>\n\n👤 {name}\n🪪 АМП-{uid:04d}\n\nВідкрийте web-панель → Учасники → картка учасника.",
                source="restoration", notification_type="system", title="Запит на відновлення",
                recipient_user_id=(admin_user.id if admin_user else None), entity_type="user", entity_id=uid,
                dedupe_key=f"restoration_request_staff:{uid}:{admin_id}",
            )
        await session.commit()

@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Незавершену дію скасовано. Відкрий /menu, щоб повернутися до головного меню.")

@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "❓ <b>Команди АМПасадорів</b>\n\n"
        "/start — запустити бота або пройти реєстрацію\n"
        "/menu — повернути головне меню\n"
        "/smart — персональні можливості за твоїми інтересами\n"
        "/help — ця довідка\n"
        "/myqr — відкрити меню персонального QR-бейджа\n"
        "/invite — отримати активне реферальне посилання\n"
        "/cancel — скасувати незавершену адміністративну форму (для координаторів/адмінів)\n\n"
        "🏠 «Головна» показує твій прогрес, серію, найближчу подію, актуальний квест, звернення та персональні можливості.\n"
        "🚀 «Долучитися» збирає події, квести, волонтерство, активності, ідеї та опитування.\n"
        "👤 «Мій профіль» — XP, ліга, серії, цілі, бейджі, винагороди й запрошення.\n\n"
        "Для відмітки на події адміністратор сканує <b>персональний QR-бейдж</b> учасника через QR-сканер."
    )

@router.message(Command("menu"))
async def menu(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user:
            await message.answer("Спочатку натисніть /start")
            return
        await _show_access(message, user, db)

@router.callback_query(F.data == "reg:resume")
async def registration_resume(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    async with db.session_factory() as session:
        row = await get_registration_journey(session, call.from_user.id)
        if not row or row.current_step not in REGISTRATION_STATE_BY_STEP:
            await call.answer("Немає незавершеної анкети", show_alert=True)
            return
        data = decrypt_draft(settings.web_session_secret, row.draft_ciphertext)
        if row.start_payload and not data.get("start_payload"):
            data["start_payload"] = row.start_payload
    await state.clear()
    await state.set_data(data)
    await state.set_state(REGISTRATION_STATE_BY_STEP[row.current_step])
    await call.message.answer("▶️ Продовжуємо реєстрацію.")
    await _send_registration_prompt(call.message, row.current_step, db)
    await call.answer()

@router.callback_query(F.data == "reg:restart")
async def registration_restart(call: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    async with db.session_factory() as session:
        existing = await get_registration_journey(session, call.from_user.id)
        payload = existing.start_payload if existing else ""
        await restart_registration_journey(session, call.from_user.id, start_payload=payload)
        await session.commit()
    await state.clear()
    if payload:
        await state.update_data(start_payload=payload)
    await state.set_state(RegistrationState.privacy_notice)
    await call.message.answer("🔄 Починаємо анкету спочатку.")
    await _send_registration_prompt(call.message, "privacy_notice", db)
    await call.answer()
