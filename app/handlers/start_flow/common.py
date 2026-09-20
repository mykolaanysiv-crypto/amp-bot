from __future__ import annotations

from ...time_utils import clock

from datetime import datetime, timedelta
import logging
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

from ...config import Settings
from ...observability import log_extra
from ...db import Database
from ...keyboards import event_detail_keyboard, main_menu, registration_phone_keyboard
from ...model_domains import ConsentHistory, Event, EventRegistration, SettlementReference, User, UserRole, UserStatus
from ...profile_data import MEDIA_CONSENT_VERSION, PRIVACY_NOTICE_VERSION, VULNERABILITY_OPTIONS, dump_vulnerabilities, parse_vulnerability_numbers, privacy_notice_text, vulnerability_prompt
from ...domain_services import (
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
from ...states import AdminEventScannerState, RegistrationState, RestorationState
from ...ui_labels import lifecycle_status_label
from ...reliability import queue_telegram_delivery
from ...settlements import canonicalize_settlement_text, resolve_canonical_settlement, settlement_key
from ...registration_ux import (
    decrypt_draft, get_registration_journey, mark_registration_submitted,
    registration_progress, restart_registration_journey, save_registration_checkpoint,
)

router = Router(name="start")


async def _safe_edit_reply_markup(call: CallbackQuery, reply_markup, *, error_code: str) -> None:
    try:
        await call.message.edit_reply_markup(reply_markup=reply_markup)
    except Exception as exc:
        logging.getLogger("amp.registration").debug(
            "Не вдалося оновити inline markup під час реєстрації",
            extra=log_extra(error_code, tg_id=call.from_user.id, exception_type=type(exc).__name__),
        )

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
        from .. import participant
        await participant.overview(message, db)
        return
    await message.answer(
        f"🚀 Вітаємо в АМП XP!\nРоль: <b>{ROLE_LABELS.get(user.role, user.role)}</b>",
        reply_markup=main_menu(user.role, user.staff_permissions_json),
    )
