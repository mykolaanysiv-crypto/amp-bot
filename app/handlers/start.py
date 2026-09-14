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
from ..models import ConsentHistory, Event, EventRegistration, SettlementReference, User, UserRole, UserStatus
from ..profile_data import MEDIA_CONSENT_VERSION, PRIVACY_NOTICE_VERSION, VULNERABILITY_OPTIONS, dump_vulnerabilities, parse_vulnerability_numbers, privacy_notice_text, vulnerability_prompt
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
from ..settlements import canonicalize_settlement_text, resolve_canonical_settlement, settlement_key
from ..registration_ux import (
    decrypt_draft, get_registration_journey, mark_registration_submitted,
    registration_progress, restart_registration_journey, save_registration_checkpoint,
)

router = Router(name="start")

ROLE_LABELS = {
    UserRole.PARTICIPANT.value: "Учасник",
    UserRole.AMBASSADOR.value: "АМПасадор",
    UserRole.COORDINATOR.value: "Координатор",
    UserRole.ADMIN.value: "Адміністратор",
    UserRole.SUPERADMIN.value: "Суперадміністратор",
}


REGISTRATION_STATE_BY_STEP = {
    "privacy_notice": RegistrationState.privacy_notice,
    "last_name": RegistrationState.last_name,
    "first_name": RegistrationState.first_name,
    "phone": RegistrationState.phone,
    "email": RegistrationState.email,
    "settlement": RegistrationState.settlement,
    "birth_date": RegistrationState.birth_date,
    "gender": RegistrationState.gender,
    "vulnerabilities": RegistrationState.vulnerabilities,
    "vulnerability_other": RegistrationState.vulnerability_other,
    "media_consent": RegistrationState.media_consent,
}


def _privacy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продовжити", callback_data="reg:privacy:1")],
        [InlineKeyboardButton(text="✖️ Не продовжувати", callback_data="reg:privacy:2")],
    ])


def _gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👩 Жіноча", callback_data="reg:gender:female"), InlineKeyboardButton(text="👨 Чоловіча", callback_data="reg:gender:male")],
        [InlineKeyboardButton(text="🧑 Інша / самовизначення", callback_data="reg:gender:other")],
        [InlineKeyboardButton(text="🙈 Не бажаю зазначати", callback_data="reg:gender:prefer_not_say")],
    ])


def _vulnerability_keyboard(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    selected_set = set(selected or [])
    rows = []
    for number, code, label_text in VULNERABILITY_OPTIONS:
        mark = "✅" if code in selected_set else "▫️"
        short = label_text if len(label_text) <= 38 else label_text[:35].rstrip() + "…"
        rows.append([InlineKeyboardButton(text=f"{mark} {number}. {short}", callback_data=f"reg:vuln:{number}")])
    rows.append([InlineKeyboardButton(text="🙈 Не бажаю зазначати", callback_data="reg:vuln:private")])
    rows.append([InlineKeyboardButton(text="➡️ Готово", callback_data="reg:vuln:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _media_consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так", callback_data="reg:media:1"),
        InlineKeyboardButton(text="❌ Ні", callback_data="reg:media:0"),
    ]])


def _resume_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продовжити реєстрацію", callback_data="reg:resume")],
        [InlineKeyboardButton(text="🔄 Почати спочатку", callback_data="reg:restart")],
    ])


async def _settlement_keyboard(session, query: str = "") -> InlineKeyboardMarkup:
    stmt = select(SettlementReference).where(SettlementReference.active == True)  # noqa: E712
    rows = list((await session.scalars(stmt.order_by(SettlementReference.sort_order.asc(), SettlementReference.canonical_name.asc()))).all())
    q = settlement_key(query)
    if q:
        ranked = []
        for row in rows:
            key = settlement_key(row.canonical_name)
            if key.startswith(q): score = 0
            elif q in key: score = 1
            else: continue
            ranked.append((score, row.sort_order, row.canonical_name, row))
        rows = [x[-1] for x in sorted(ranked)[:6]]
    else:
        rows = rows[:6]
    buttons = [[InlineKeyboardButton(text=f"📍 {row.canonical_name}", callback_data=f"reg:settlement:{row.id}")] for row in rows]
    if not q:
        buttons.append([InlineKeyboardButton(text="✍️ Інший населений пункт", callback_data="reg:settlement:other")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _checkpoint(state: FSMContext, db: Database, settings: Settings, tg_id: int, step: str, *, mark_consent: bool = False, mark_profile: bool = False) -> None:
    data = await state.get_data()
    async with db.session_factory() as session:
        await save_registration_checkpoint(
            session, tg_id=tg_id, step=step, data=data, secret=settings.web_session_secret,
            start_payload=str(data.get("start_payload") or ""), mark_consent=mark_consent, mark_profile=mark_profile,
        )
        await session.commit()


async def _send_registration_prompt(message: Message, step: str, db: Database) -> None:
    progress = registration_progress(step)
    if step == "privacy_notice":
        await message.answer(f"{progress}\n\n{privacy_notice_text()}", reply_markup=_privacy_keyboard())
    elif step == "last_name":
        await message.answer(f"{progress}\n\n👤 Напишіть ваше <b>прізвище</b>.\nНаприклад: <b>Прохоренко</b>.")
    elif step == "first_name":
        await message.answer(f"{progress}\n\n👤 Тепер напишіть <b>ім’я</b>.\nНаприклад: <b>Микола</b>.")
    elif step == "phone":
        await message.answer(f"{progress}\n\n📱 <b>Номер телефону</b>\nНадішліть контакт кнопкою нижче або введіть номер вручну, наприклад <code>+380671234567</code>.", reply_markup=registration_phone_keyboard())
    elif step == "email":
        await message.answer(f"{progress}\n\n✉️ <b>Електронна пошта</b>\nВведіть адресу, наприклад <code>name@example.com</code>.", reply_markup=ReplyKeyboardRemove())
    elif step == "settlement":
        async with db.session_factory() as session:
            kb = await _settlement_keyboard(session)
        await message.answer(f"{progress}\n\n📍 <b>Населений пункт</b>\nОберіть зі списку або почніть вводити назву — бот запропонує збіги.", reply_markup=kb)
    elif step == "birth_date":
        await message.answer(f"{progress}\n\n🎂 <b>Дата народження</b>\nВкажіть у форматі <b>ДД.ММ.РРРР</b>, наприклад <b>17.04.2010</b>.")
    elif step == "gender":
        await message.answer(f"{progress}\n\n⚧ <b>Стать</b>\nОберіть один варіант. Дані використовуються лише для агрегованої статистики.", reply_markup=_gender_keyboard())
    elif step == "vulnerabilities":
        await message.answer(
            f"{progress}\n\n🧩 <b>Соціальний статус / категорії вразливості</b>\n\n"
            "Можна обрати кілька варіантів кнопками. Дані використовуються лише для агрегованої аналітики. "
            "Якщо не хочете повідомляти — оберіть «Не бажаю зазначати».\n\n"
            "Позначте потрібні варіанти та натисніть <b>«Готово»</b>.",
            reply_markup=_vulnerability_keyboard(),
        )
    elif step == "vulnerability_other":
        await message.answer(f"{registration_progress('vulnerabilities')}\n\n✍️ Коротко уточніть назву категорії, яку обрали як «Інша».")
    elif step == "media_consent":
        await message.answer(
            f"{progress}\n\n📷 <b>Фото- та відеозйомка</b>\nЧи погоджуєтесь на фото/відеозйомку під час заходів АМП та використання цих матеріалів у комунікаціях АМП?",
            reply_markup=_media_consent_keyboard(),
        )


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
        reply_markup=main_menu(user.role, user.staff_permissions_json),
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
            # v1.11.0: registration checkpoints survive /menu, /start and dyno restarts.
            journey = await get_registration_journey(session, message.from_user.id)
            resumable = bool(journey and journey.current_step in REGISTRATION_STATE_BY_STEP)
            if resumable:
                await state.clear()
                if payload and not journey.start_payload:
                    journey.start_payload = payload[:180]
                    journey.updated_at = datetime.utcnow()
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


async def _accept_privacy(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    await state.update_data(privacy_notice_version=PRIVACY_NOTICE_VERSION, privacy_acknowledged_at=datetime.utcnow().isoformat())
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
                row.updated_at = datetime.utcnow()
                await session.commit()
        await state.clear()
        await call.message.answer("Реєстрацію не продовжено. Ви можете повернутися пізніше командою /start.")
        await call.answer()
        return
    msg = call.message.model_copy(update={"from_user": call.from_user})
    await _accept_privacy(msg, state, db, settings)
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await call.answer()


@router.message(RegistrationState.privacy_notice)
async def reg_privacy_notice(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    raw = (message.text or "").strip().lower()
    if raw in {"2", "ні", "no"}:
        async with db.session_factory() as session:
            row = await get_registration_journey(session, message.from_user.id)
            if row:
                row.current_step = "declined"; row.draft_ciphertext = ""; row.updated_at = datetime.utcnow()
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
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
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
    today = datetime.now().date()
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
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
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
        try: await call.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        await _send_registration_prompt(msg, "media_consent", db)
        await call.answer("Збережено без зазначення категорії")
        return
    if action == "done":
        if not selected:
            await call.answer("Оберіть хоча б один варіант або «Не бажаю зазначати».", show_alert=True)
            return
        needs_other = "other" in selected
        msg = call.message.model_copy(update={"from_user": call.from_user})
        try: await call.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
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
    try: await call.message.edit_reply_markup(reply_markup=_vulnerability_keyboard(selected))
    except Exception: pass
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
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
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

