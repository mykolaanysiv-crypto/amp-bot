from __future__ import annotations

from datetime import datetime, timedelta
import json
from html import escape
from urllib.parse import quote
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove, WebAppInfo
from sqlalchemy import select

from ..config import Settings
from ..db import Database
from ..keyboards import event_detail_keyboard, main_menu, registration_phone_keyboard
from ..models import ConsentHistory, Event, EventRegistration, User, UserRole, UserStatus
from ..profile_data import MEDIA_CONSENT_VERSION, PRIVACY_NOTICE_VERSION, dump_vulnerabilities, parse_vulnerability_numbers, privacy_notice_text, vulnerability_prompt
from ..services import (
    age_on,
    checkin_for_event,
    event_checkin_window,
    admin_scan_event_participant,
    confirm_single_event_attendance,
    create_referral_for_user,
    ensure_user_tokens,
    get_user_by_tg,
    log_audit,
    season_xp,
    xp_total,
)
from ..states import AdminEventScannerState, RegistrationState, RestorationState
from ..ui_labels import lifecycle_status_label
from ..reliability import queue_telegram_delivery
from ..settlements import canonicalize_settlement_text, resolve_canonical_settlement

router = Router(name="start")

ROLE_LABELS = {
    UserRole.PARTICIPANT.value: "Учасник",
    UserRole.AMBASSADOR.value: "АМПасадор",
    UserRole.COORDINATOR.value: "Координатор",
    UserRole.ADMIN.value: "Адміністратор",
    UserRole.SUPERADMIN.value: "Суперадміністратор",
}


def _valid_person_name(value: str) -> bool:
    """Validate a human name without silently correcting the participant's input."""
    value = value.strip()
    letters = [ch for ch in value if ch.isalpha()]
    if len(letters) < 2 or not value or not value[0].isalpha() or not value[0].isupper():
        return False
    return all(ch.isalpha() or ch in " -'’ʼ" for ch in value)


def _normalize_phone(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("+"):
        prefix = "+"
        body = text[1:]
    else:
        prefix = ""
        body = text
    digits = re.sub(r"[\s()\-.]", "", body)
    if not digits.isdigit() or not 10 <= len(digits) <= 15:
        return None
    return prefix + digits


async def _show_access(message: Message, user: User, db: Database | None = None) -> None:
    if user.status == UserStatus.BLOCKED.value:
        until = f" до <b>{user.blocked_until.strftime('%d.%m.%Y %H:%M')}</b>" if user.blocked_until else ""
        reason = f"\nПричина: {user.block_reason}" if user.block_reason else ""
        await message.answer(f"⛔ Ваш профіль тимчасово обмежено{until}.{reason}\nЯкщо вважаєте це помилкою — зверніться до команди АМП.")
        return
    if user.status == UserStatus.PENDING.value:
        consent = "\n👪 Потрібне підтвердження згоди батьків/законного представника." if user.parental_consent_required and not user.parental_consent_confirmed else ""
        await message.answer("⏳ Реєстрацію отримано. Профіль очікує підтвердження адміністратора." + consent, reply_markup=ReplyKeyboardRemove())
        return
    if user.status == UserStatus.INACTIVE.value:
        await message.answer(
            "💤 Ваш профіль позначено як <b>неактивний</b>. Дані, XP та історія участі збережені. "
            "Якщо ви повернулися до АМП — зверніться до адміністратора для повторної активації.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if user.status == UserStatus.DELETED.value:
        if user.restoration_request_status == "pending":
            await message.answer(
                "🗑 <b>Ваш акаунт видалено з активного доступу.</b> Дані та історія участі збережені.\n\n"
                "♻️ Запит на відновлення вже надіслано суперадміністратору. Очікуйте рішення.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer(
                "🗑 <b>Ваш акаунт видалено.</b> Доступ до функцій бота закрито, але дані та історія участі збережені.\n\n"
                "Хочете подати запит на відновлення?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ Так, відновити акаунт", callback_data="restore:start")]]),
            )
        return
    if user.status == UserStatus.DELETED_PERMANENT.value:
        await message.answer(
            "⛔ <b>Ваш акаунт видалено без можливості відновлення.</b>\n\n"
            "Дані та історія участі зберігаються в системі для обліку й звітності, але доступ до бота закрито назавжди.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if db is not None:
        # Import lazily to avoid a router import cycle. Active participants land
        # directly on the useful "Мій АМП сьогодні" screen.
        from . import participant
        await participant.overview(message, db)
        return
    await message.answer(
        f"🚀 Вітаємо в АМП XP!\nРоль: <b>{ROLE_LABELS.get(user.role, user.role)}</b>",
        reply_markup=main_menu(user.role),
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
                from ..gamification import get_level
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
                last_activity_at=datetime.utcnow(),
            )
            session.add(user)
            await session.flush()
            await ensure_user_tokens(session, user)
            await session.commit()
            await _show_access(message, user, db)
            return

        if not user:
            await state.clear()
            await state.set_state(RegistrationState.privacy_notice)
            if payload:
                await state.update_data(start_payload=payload)
            await message.answer(
                "👋 Вітаємо в <b>АМПасадори / АМП XP</b>!\n\n"
                "Перед анкетою коротко пояснюємо, які дані збираються і для чого.\n\n"
                + privacy_notice_text()
            )
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
                if event.status in {"open", "postponed"} and event.starts_at >= datetime.now():
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
        user.restoration_requested_at=datetime.utcnow()
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


@router.message(RegistrationState.privacy_notice)
async def reg_privacy_notice(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw == "2":
        await state.clear()
        await message.answer("Реєстрацію не продовжено. Ви можете повернутися пізніше командою /start.")
        return
    if raw != "1":
        await message.answer("Оберіть <b>1 — продовжити</b> або <b>2 — не продовжувати</b>.\n\n" + privacy_notice_text())
        return
    await state.update_data(
        privacy_notice_version=PRIVACY_NOTICE_VERSION,
        privacy_acknowledged_at=datetime.utcnow().isoformat(),
    )
    await state.set_state(RegistrationState.last_name)
    await message.answer(
        "✅ Дякуємо. Реєстраційна анкета заповнюється послідовно, і <b>всі її пункти є обов’язковими</b>.\n"
        "Прізвище та ім’я потрібно писати <b>з великої літери</b>.\n\n"
        "👤 Напишіть ваше <b>прізвище</b>."
    )


@router.message(RegistrationState.last_name)
async def reg_last_name(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) < 2:
        await message.answer("Вкажіть, будь ласка, прізвище.")
        return
    if not _valid_person_name(value):
        await message.answer("❌ Введіть <b>прізвище з великої літери</b> (наприклад: Прохоренко). Спробуйте ще раз.")
        return
    await state.update_data(last_name=value)
    await state.set_state(RegistrationState.first_name)
    await message.answer("👤 Тепер напишіть <b>ім’я з великої літери</b>.")


@router.message(RegistrationState.first_name)
async def reg_first_name(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) < 2:
        await message.answer("Вкажіть, будь ласка, ім’я.")
        return
    if not _valid_person_name(value):
        await message.answer("❌ Введіть <b>ім’я з великої літери</b> (наприклад: Микола). Спробуйте ще раз.")
        return
    await state.update_data(first_name=value)
    await state.set_state(RegistrationState.phone)
    await message.answer("📱 <b>Номер телефону — обов’язкове поле.</b> Надішліть контакт кнопкою нижче або введіть номер вручну, наприклад: <code>+380671234567</code>.", reply_markup=registration_phone_keyboard())


@router.message(RegistrationState.phone, F.contact)
async def reg_phone_contact(message: Message, state: FSMContext) -> None:
    phone = _normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("❌ Не вдалося прочитати номер. Введіть його вручну, наприклад: <code>+380671234567</code>.")
        return
    await state.update_data(phone=phone)
    await state.set_state(RegistrationState.email)
    await message.answer("✉️ <b>Електронна пошта — обов’язкове поле.</b> Вкажіть email, наприклад: <code>name@example.com</code>.", reply_markup=ReplyKeyboardRemove())


@router.message(RegistrationState.phone)
async def reg_phone_text(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    phone = _normalize_phone(raw)
    if not phone:
        await message.answer("❌ Введіть коректний <b>номер телефону</b> (10–15 цифр), наприклад: <code>+380671234567</code>.")
        return
    await state.update_data(phone=phone)
    await state.set_state(RegistrationState.email)
    await message.answer("✉️ <b>Електронна пошта — обов’язкове поле.</b> Вкажіть email, наприклад: <code>name@example.com</code>.", reply_markup=ReplyKeyboardRemove())


@router.message(RegistrationState.email)
async def reg_email(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
        await message.answer("❌ Електронна пошта є обов’язковою. Введіть коректну адресу, наприклад: <b>name@example.com</b>.")
        return
    email = raw.lower()
    await state.update_data(email=email)
    await state.set_state(RegistrationState.settlement)
    await message.answer("📍 <b>Населений пункт — обов’язкове поле.</b> З якого ви населеного пункту?")


@router.message(RegistrationState.settlement)
async def reg_settlement(message: Message, state: FSMContext) -> None:
    settlement = canonicalize_settlement_text(message.text) or ""
    if len(settlement) < 2:
        await message.answer("❌ Вкажіть населений пункт. Це обов’язкове поле реєстрації.")
        return
    await state.update_data(settlement=settlement)
    await state.set_state(RegistrationState.birth_date)
    await message.answer("🎂 <b>Дата народження — обов’язкове поле.</b> Вкажіть її у форматі <b>ДД.ММ.РРРР</b>.\nЦе потрібно для вікових правил участі та автоматичного привітання з днем народження.")


@router.message(RegistrationState.birth_date)
async def reg_birth_date(message: Message, state: FSMContext) -> None:
    try:
        birth_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("❌ Дата народження обов’язкова. Введіть коректну дату у форматі <b>ДД.ММ.РРРР</b>, наприклад: <b>17.04.2010</b>.")
        return
    if birth_date > datetime.now().date():
        await message.answer("Дата народження не може бути в майбутньому.")
        return
    if age_on(birth_date) > 120:
        await message.answer("Перевірте, будь ласка, рік народження.")
        return
    await state.update_data(birth_date=birth_date.isoformat())
    await state.set_state(RegistrationState.gender)
    await message.answer(
        "⚧ <b>Вкажіть стать</b> — це обов’язковий крок для внутрішньої статистики та звітності:\n\n"
        "1 — Жіноча\n"
        "2 — Чоловіча\n"
        "3 — Інша / самовизначення\n"
        "4 — Не бажаю зазначати\n\n"
        "Надішліть номер варіанта."
    )


@router.message(RegistrationState.gender)
async def reg_gender(message: Message, state: FSMContext) -> None:
    mapping = {"1": "female", "2": "male", "3": "other", "4": "prefer_not_say"}
    value = mapping.get((message.text or "").strip())
    if not value:
        await message.answer("Оберіть один варіант: <b>1, 2, 3 або 4</b>.")
        return
    await state.update_data(gender=value)
    await state.set_state(RegistrationState.vulnerabilities)
    await message.answer(vulnerability_prompt())


@router.message(RegistrationState.vulnerabilities)
async def reg_vulnerabilities(message: Message, state: FSMContext) -> None:
    try:
        codes, needs_other = parse_vulnerability_numbers(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {exc}\n\n{vulnerability_prompt()}")
        return
    await state.update_data(vulnerability_codes=codes)
    if needs_other:
        await state.set_state(RegistrationState.vulnerability_other)
        await message.answer("✍️ Ви обрали «Інша категорія». <b>Обов’язково</b> коротко уточніть її назву.")
        return
    await state.update_data(vulnerability_other="")
    await state.set_state(RegistrationState.media_consent)
    await message.answer(
        "📷 <b>Згода на фото- та відеозйомку</b>\n\n"
        "Чи погоджуєтесь ви на фото- та відеозйомку під час заходів АМП та використання цих матеріалів у комунікаціях АМП?\n\n"
        "1 — Так\n2 — Ні"
    )


@router.message(RegistrationState.vulnerability_other)
async def reg_vulnerability_other(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 2 or raw.lower() == "пропустити":
        await message.answer("❌ Уточнення для «Інша категорія» є обов’язковим. Введіть коротку назву категорії.")
        return
    other = raw[:180]
    await state.update_data(vulnerability_other=other)
    await state.set_state(RegistrationState.media_consent)
    await message.answer(
        "📷 <b>Згода на фото- та відеозйомку</b>\n\n"
        "Чи погоджуєтесь ви на фото- та відеозйомку під час заходів АМП та використання цих матеріалів у комунікаціях АМП?\n\n"
        "1 — Так\n2 — Ні"
    )


@router.message(RegistrationState.media_consent)
async def reg_media_consent(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    raw = (message.text or "").strip()
    if raw not in {"1", "2"}:
        await message.answer("Оберіть: <b>1 — Так</b> або <b>2 — Ні</b>.")
        return
    await state.update_data(media_consent=(raw == "1"))
    await _complete_registration(message, state, db, settings, bot)


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
            media_consent_recorded_at=datetime.utcnow(),
            privacy_notice_version=data.get("privacy_notice_version") or PRIVACY_NOTICE_VERSION,
            privacy_acknowledged_at=datetime.fromisoformat(data["privacy_acknowledged_at"]) if data.get("privacy_acknowledged_at") else datetime.utcnow(),
            role=UserRole.PARTICIPANT.value,
            status=UserStatus.PENDING.value,
            registration_review_status="pending",
            parental_consent_required=minor,
            parental_consent_confirmed=False,
            parental_consent_status="pending" if minor else "not_required",
            last_activity_at=datetime.utcnow(),
        )
        session.add(user)
        await session.flush()
        session.add(ConsentHistory(
            user_id=user.id,
            consent_type="media",
            status=user.media_consent_status,
            version=user.media_consent_version,
            changed_by_label="Telegram registration",
            changed_at=user.media_consent_recorded_at or datetime.utcnow(),
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

