from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import parse_qs, quote, urlparse
import re

import qrcode
from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from ..config import Settings
from ..db import Database
from ..gamification import get_level, normalize_event_xp, normalize_manual_xp, normalize_quest_xp, normalize_task_xp
from ..analytics import analytics_bot_text, build_analytics
from ..reliability import queue_telegram_delivery
from ..opportunity_matching import refresh_matches_for_opportunity
from ..keyboards import ADMIN_ROLES, admin_menu, admin_section_menu, compact_button_text, main_menu, pending_user_keyboard
from ..permissions import effective_permissions, has_permission
from ..models import (
    ActivityApplication,
    ActivityType,
    BanRecord,
    Badge,
    ConsentHistory,
    Event,
    EventRegistration,
    Opportunity,
    Quest,
    QuestParticipation,
    Reward,
    RewardClaim,
    User,
    UserBadge,
    UserRole,
    UserStatus,
    VolunteerTask,
    VolunteerTaskParticipation,
)
from ..services import (
    add_active_users_to_default_team,
    add_xp,
    complete_activity_application,
    confirm_event_attendance,
    event_checkin_window,
    admin_scan_event_participant,
    create_event,
    evaluate_automatic_badges,
    export_excel,
    get_user,
    get_user_by_tg,
    log_audit,
    reward_referral_if_ready,
    xp_total,
)
from ..ui_labels import activity_status_label, label
from ..states import (
    AdminBadgeAwardState,
    AdminBanState,
    AdminBroadcastState,
    AdminEventState,
    AdminEventScannerState,
    AdminOpportunityState,
    AdminQuestState,
    AdminRewardState,
    AdminTaskState,
    AdminXPState,
)

router = Router(name="admin")


def _callback_permission(data: str | None) -> str | None:
    value = str(data or "")
    rules = (
        (("admin:pending", "admin:consent:", "admin:approve:"), "participants.approve"),
        (("admin:block:", "admin:moderation", "admin:ban_"), "moderation.manage"),
        (("admin:add_xp",), "xp.award"),
        (("admin:create_event",), "events.create"),
        (("admin:event_scanner", "admin:event_qr", "admin:event_share", "admin:attendance", "admin:confirm_event:"), "events.edit"),
        (("admin:create_quest", "admin:quest_approvals", "admin:approve_quest:"), "quests.manage"),
        (("admin:award_badge", "admin:create_reward", "admin:reward_claims", "admin:fulfill_reward:", "admin:reject_reward:"), "gamification.manage"),
        (("admin:activity_",), "activities.manage"),
        (("admin:create_task", "admin:task_approvals", "admin:approve_task_part:"), "volunteer.manage"),
        (("admin:create_opportunity",), "opportunities.manage"),
        (("admin:analytics",), "analytics.view"),
        (("admin:export",), "reports.basic_export"),
        (("admin:broadcast",), "broadcast.send"),
    )
    for prefixes, permission in rules:
        if any(value.startswith(prefix) for prefix in prefixes):
            return permission
    return None


class AdminCallbackPermissionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        permission = _callback_permission(getattr(event, "data", None))
        if permission:
            db = data.get("db")
            if db is not None:
                async with db.session_factory() as session:
                    user = await get_user_by_tg(session, event.from_user.id)
                    allowed = bool(
                        user and user.status == UserStatus.ACTIVE.value and user.role in ADMIN_ROLES
                        and has_permission(user.role, user.staff_permissions_json, permission)
                    )
                if not allowed:
                    await event.answer("Недостатньо прав для цієї дії", show_alert=True)
                    return None
        return await handler(event, data)


router.callback_query.outer_middleware(AdminCallbackPermissionMiddleware())


async def _queue_new_entity_notice(session, text: str, source: str, dedupe_prefix: str) -> int:
    users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value, User.tg_id.is_not(None)))).all())
    for user in users:
        await queue_telegram_delivery(session,user.tg_id,text,source=source,dedupe_key=f"{dedupe_prefix}:{user.id}")
    return len(users)




async def _queue_user_notice(
    session, user: User | None, text: str, *, source: str = "admin", title: str | None = None,
    entity_type: str | None = None, entity_id: int | None = None, dedupe_key: str | None = None,
) -> None:
    """Send participant-facing admin notifications through v1.9 Notification Center."""
    if not user or not user.tg_id:
        return
    await queue_telegram_delivery(
        session, user.tg_id, text, source=source, title=title, recipient_user_id=user.id,
        entity_type=entity_type, entity_id=entity_id, dedupe_key=dedupe_key, parse_mode="HTML",
    )

async def _admin(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role not in ADMIN_ROLES:
        return None
    return user


def _staff_permissions(user: User) -> frozenset[str]:
    return effective_permissions(user.role, user.staff_permissions_json)


async def _require_permission(target: Message | CallbackQuery, db: Database, permission: str) -> User | None:
    async with db.session_factory() as session:
        admin = await _admin(session, target.from_user.id)
        allowed = bool(admin and has_permission(admin.role, admin.staff_permissions_json, permission))
    if not allowed:
        if isinstance(target, CallbackQuery):
            await target.answer("Недостатньо прав для цієї дії", show_alert=True)
        else:
            await target.answer("⛔ Недостатньо прав для цієї дії.")
        return None
    return admin


async def _full_admin(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        return None
    return user


async def _super_admin(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role != UserRole.SUPERADMIN.value:
        return None
    return user

async def _require_admin(target: Message | CallbackQuery, db: Database) -> User | None:
    async with db.session_factory() as session:
        admin = await _admin(session, target.from_user.id)
    if not admin:
        if isinstance(target, CallbackQuery):
            await target.answer("Недостатньо прав", show_alert=True)
        else:
            await target.answer("⛔ Недостатньо прав.")
    return admin


@router.message(F.text == "🛠 Адмін-панель")
async def admin_panel(message: Message, db: Database) -> None:
    admin = await _require_admin(message, db)
    if not admin:
        return
    await message.answer(
        "🛠 <b>Панель адміністратора АМПасадорів</b>\n\nОберіть потрібний розділ:",
        reply_markup=admin_menu(admin.role, _staff_permissions(admin)),
    )


_ADMIN_SECTION_TITLES = {
    "events": "📅 <b>Події</b>",
    "activities": "🎯 <b>Активності</b>",
    "gamification": "🏆 <b>XP та винагороди</b>",
    "people": "👥 <b>Учасники</b>",
    "data": "📊 <b>Аналітика й комунікація</b>",
}


async def _show_admin_menu(call: CallbackQuery, db: Database, *, section: str | None = None) -> None:
    admin = await _require_admin(call, db)
    if not admin:
        return
    if section and section not in _ADMIN_SECTION_TITLES:
        await call.answer("Невідомий розділ", show_alert=True)
        return

    if section:
        text = f"{_ADMIN_SECTION_TITLES[section]}\n\nОберіть дію:"
        markup = admin_section_menu(admin.role, section, _staff_permissions(admin))
    else:
        text = "🛠 <b>Панель адміністратора АМПасадорів</b>\n\nОберіть потрібний розділ:"
        markup = admin_menu(admin.role, _staff_permissions(admin))
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        await call.message.answer(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "admin:menu")
async def admin_menu_root(call: CallbackQuery, db: Database) -> None:
    await _show_admin_menu(call, db)


@router.callback_query(F.data.startswith("admin:section:"))
async def admin_menu_section(call: CallbackQuery, db: Database) -> None:
    await _show_admin_menu(call, db, section=call.data.rsplit(":", 1)[-1])


@router.callback_query(F.data == "admin:analytics")
async def admin_analytics(call: CallbackQuery, db: Database, settings: Settings) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Аналітика доступна адміністраторам", show_alert=True)
            return
        data = await build_analytics(session)
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Повна аналітика", url=f"{settings.public_base_url}/admin/analytics")
    builder.adjust(1)
    await call.message.answer(analytics_bot_text(data), reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data == "admin:web")
async def web_admin_link(call: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _require_admin(call, db):
        return
    await call.message.answer(
        "🌐 <b>Вебпанель адміністратора АМПасадорів</b>\n"
        f"{settings.public_base_url}/admin\n\n"
        "Доступ керується через захищені персональні web-акаунти. Паролі зберігаються лише як хеші у БД.\n"
        "Зміна пароля та 2FA: <code>/admin/account</code>."
    )
    await call.answer()


@router.callback_query(F.data == "admin:pending")
async def pending_users(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав для цієї дії", show_alert=True)
            return
        users = (await session.scalars(select(User).where(User.status == UserStatus.PENDING.value).order_by(User.created_at))).all()
        if not users:
            await call.message.answer("👥 Нових заявок немає.")
            await call.answer()
            return
        for u in users[:30]:
            age_text = u.birth_date.strftime("%d.%m.%Y") if u.birth_date else "—"
            consent = "потрібна" if u.parental_consent_required and not u.parental_consent_confirmed else "не потрібна / підтверджена"
            await call.message.answer(
                f"👤 <b>{u.full_name}</b>\nАМП-код: <code>АМП-{u.id:04d}</code>\n"
                f"Дата народження: {age_text}\nНаселений пункт: {u.settlement or '—'}\n"
                f"Згода батьків: {consent}",
                reply_markup=pending_user_keyboard(u.id, u.parental_consent_required and not u.parental_consent_confirmed, _staff_permissions(admin)),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:consent:"))
async def confirm_consent(call: CallbackQuery, db: Database) -> None:
    user_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await call.answer("Не знайдено", show_alert=True)
            return
        user.parental_consent_confirmed = True
        user.parental_consent_status = "received"
        user.parental_consent_received_at = datetime.utcnow()
        session.add(ConsentHistory(
            user_id=user.id,
            consent_type="parental",
            status="received",
            file_path=user.parental_consent_file_path,
            changed_by_label=admin.full_name or "Telegram admin",
            changed_at=user.parental_consent_received_at,
        ))
        await session.commit()
        await call.message.answer(f"👪 Згоду батьків для <b>{user.full_name}</b> позначено як підтверджену.")
        await call.answer()


@router.callback_query(F.data.startswith("admin:approve:"))
async def approve_user(call: CallbackQuery, db: Database, bot: Bot, settings: Settings) -> None:
    user_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await call.answer("Не знайдено", show_alert=True)
            return
        if user.parental_consent_required and not user.parental_consent_confirmed:
            await call.answer("Спочатку підтвердьте згоду батьків", show_alert=True)
            return
        user.status = UserStatus.ACTIVE.value
        user.registration_review_status = "approved"
        user.registration_reviewed_at = datetime.utcnow()
        user.registration_reviewed_by = admin.full_name or f"Telegram:{admin.tg_id}"
        user.registration_rejection_reason = None
        await add_active_users_to_default_team(session)
        referral_reward = await reward_referral_if_ready(session, user, settings, created_by=admin.id)
        await log_audit(session, "user_activated", admin, entity_type="user", entity_id=user.id)
        await _queue_user_notice(session, user, "✅ Ваш профіль АМП XP активовано! Відкрийте /menu.", source="user_activation", entity_type="user", entity_id=user.id, dedupe_key=f"user_activation:{user.id}")
        if referral_reward:
            inviter, reward = referral_reward
            await _queue_user_notice(
                session, inviter,
                f"🤝 Твоє запрошення спрацювало! <b>{user.full_name}</b> активовано. +{reward} XP.\n"
                "Бонус за запрошення зменшується від 10 до 1 XP у межах кварталу та оновлюється на початку нового кварталу.",
                source="referral", entity_type="user", entity_id=user.id, dedupe_key=f"referral_reward_notice:{user.id}:{inviter.id}",
            )
        await session.commit()
        await call.message.answer(f"✅ <b>{user.full_name}</b> активовано.")
        await call.answer()


@router.callback_query(F.data.startswith("admin:block:"))
async def block_user(call: CallbackQuery, db: Database, bot: Bot) -> None:
    user_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await call.answer("Не знайдено", show_alert=True)
            return
        user.status = UserStatus.BLOCKED.value
        await _queue_user_notice(session, user, "⛔ Ваш профіль АМП XP заблоковано. Зверніться до команди АМП.", source="moderation", entity_type="user", entity_id=user.id, dedupe_key=f"user_blocked:{user.id}:{datetime.utcnow().date().isoformat()}")
        await session.commit()
        await call.answer("Заблоковано")


# ---------- XP ----------
@router.callback_query(F.data == "admin:add_xp")
async def add_xp_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminXPState.user_id)
    await call.message.answer("⚡ Вкажіть числовий номер учасника (наприклад <code>24</code> для АМП-0024).")
    await call.answer()


@router.message(AdminXPState.user_id)
async def add_xp_user(message: Message, state: FSMContext, db: Database) -> None:
    try:
        user_id = int((message.text or "").replace("АМП-", "").replace("AMP-", "").lstrip("0") or "0")
    except ValueError:
        await message.answer("Вкажіть числовий номер.")
        return
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer("Учасника не знайдено.")
            return
    await state.update_data(user_id=user_id)
    await state.set_state(AdminXPState.amount)
    await message.answer("Скільки XP нарахувати? Ручний позитивний бонус — до 40 XP за одну підтверджену дію. Від’ємне число можна використати для корекції.")


@router.message(AdminXPState.amount)
async def add_xp_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число, наприклад 20.")
        return
    normalized = normalize_manual_xp(amount)
    if normalized != amount:
        if amount > 40:
            await message.answer("⚖️ Для балансу ручний позитивний бонус обмежено 40 XP за одну дію. Значення буде встановлено на 40 XP.")
        elif amount < -500:
            await message.answer("Для безпеки корекцію обмежено -500 XP за одну операцію.")
    await state.update_data(amount=normalized)
    await state.set_state(AdminXPState.description)
    await message.answer("Напишіть причину / опис нарахування.")


@router.message(AdminXPState.description)
async def add_xp_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "xp.award"):
        await state.clear()
        return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, data["user_id"])
        if not admin or not user:
            await state.clear()
            return
        total, level, leveled = await add_xp(
            session, user, data["amount"], (message.text or "").strip(), created_by=admin.id
        )
        text = f"⚡ Вам нараховано <b>{data['amount']} XP</b>\nПричина: {(message.text or '').strip()}\nВсього: <b>{total} XP</b>"
        if leveled:
            text += f"\n\n🎉 Новий рівень: <b>{level}</b>"
        await _queue_user_notice(session, user, text, source="xp_achievement", title="Нарахування XP", entity_type="user", entity_id=user.id)
        await session.commit()
        await message.answer(f"✅ {user.full_name}: {data['amount']} XP. Загалом {total} XP.")
    await state.clear()


# ---------- Events ----------
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
    except Exception:
        pass
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
                Event.starts_at >= datetime.utcnow() - timedelta(hours=12),
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
                Event.starts_at >= datetime.utcnow() - timedelta(hours=12),
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
                Event.starts_at >= datetime.utcnow() - timedelta(hours=12),
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
                Event.starts_at >= datetime.utcnow(),
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


def _single_button(text: str, data: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=compact_button_text(text), callback_data=data)]])

def _two_buttons(text1: str, data1: str, text2: str, data2: str):
    b = InlineKeyboardBuilder()
    b.button(text=compact_button_text(text1), callback_data=data1)
    b.button(text=compact_button_text(text2), callback_data=data2)
    b.adjust(1)
    return b.as_markup()



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


# ---------- Quests ----------
@router.callback_query(F.data == "admin:create_quest")
async def quest_create_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminQuestState.title)
    await call.message.answer("🎯 Назва квесту?")
    await call.answer()


@router.message(AdminQuestState.title)
async def q_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminQuestState.description)
    await message.answer("Опиши умови квесту.")


@router.message(AdminQuestState.description)
async def q_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminQuestState.xp_reward)
    await message.answer("Нагорода XP? Для індивідуального квесту допустимо 10–35 XP.")


@router.message(AdminQuestState.xp_reward)
async def q_xp(message: Message, state: FSMContext) -> None:
    try:
        xp = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число.")
        return
    xp = normalize_quest_xp(xp, "individual")
    await state.update_data(xp_reward=xp)
    await state.set_state(AdminQuestState.deadline_day)
    await message.answer("📅 День дедлайну квесту (1–31) або слово <b>немає</b>, якщо дедлайн не потрібен.")


async def _finish_tg_quest(message: Message, state: FSMContext, db: Database, ends: datetime | None) -> None:
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            return
        quest=Quest(title=data["title"], description=data["description"], xp_reward=data["xp_reward"], ends_at=ends, created_by=admin.id)
        session.add(quest); await session.flush()
        await _queue_new_entity_notice(session,f"🎯 <b>Новий квест</b>\n\n<b>{quest.title}</b>\n⚡ {quest.xp_reward} XP\n\nВідкрий «🎯 Квести» у боті, щоб долучитися.","quest_created",f"quest_created:{quest.id}")
        await session.commit()
    await state.clear()
    text = "✅ Квест створено."
    if ends:
        text += f"\n📅 Дедлайн: {ends.strftime('%d.%m.%Y')} о {ends.strftime('%H:%M')}"
    await message.answer(text)


@router.message(AdminQuestState.deadline_day)
async def q_deadline_day(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip().lower()
    if raw == "немає":
        await _finish_tg_quest(message, state, db, None)
        return
    try:
        day = int(raw)
        if not 1 <= day <= 31:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть день числом від 1 до 31 або «немає».")
        return
    await state.update_data(deadline_day=day)
    await state.set_state(AdminQuestState.deadline_month)
    await message.answer("📅 Місяць дедлайну числом від 1 до 12.")


@router.message(AdminQuestState.deadline_month)
async def q_deadline_month(message: Message, state: FSMContext) -> None:
    try:
        month = int((message.text or "").strip())
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть місяць числом від 1 до 12.")
        return
    await state.update_data(deadline_month=month)
    await state.set_state(AdminQuestState.deadline_year)
    await message.answer("📅 Рік дедлайну, наприклад <b>2026</b>.")


@router.message(AdminQuestState.deadline_year)
async def q_deadline_year(message: Message, state: FSMContext) -> None:
    try:
        year = int((message.text or "").strip())
        if not 2026 <= year <= 2100:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть рік від 2026 до 2100.")
        return
    await state.update_data(deadline_year=year)
    await state.set_state(AdminQuestState.deadline_time)
    await message.answer("🕐 Час дедлайну у форматі <b>ГГ:ХХ</b>, наприклад 18:00.")


@router.message(AdminQuestState.deadline_time)
async def q_deadline_time(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "quests.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    try:
        hour, minute = [int(x) for x in raw.split(":", 1)]
        ends = datetime(int(data["deadline_year"]), int(data["deadline_month"]), int(data["deadline_day"]), hour, minute)
    except Exception:
        await message.answer("Некоректна дата або час. Введіть час у форматі ГГ:ХХ, наприклад 18:00.")
        return
    await _finish_tg_quest(message, state, db, ends)


@router.callback_query(F.data == "admin:quest_approvals")
async def quest_approvals(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        rows = (
            await session.execute(
                select(QuestParticipation, User, Quest)
                .join(User, User.id == QuestParticipation.user_id)
                .join(Quest, Quest.id == QuestParticipation.quest_id)
                .where(QuestParticipation.status == "completed")
                .order_by(QuestParticipation.completed_at)
            )
        ).all()
        if not rows:
            await call.message.answer("🎯 Немає квестів на підтвердженні.")
        for part, user, quest in rows[:30]:
            await call.message.answer(
                f"🎯 <b>{quest.title}</b>\n👤 {user.full_name}\n⚡ {quest.xp_reward} XP",
                reply_markup=_single_button("✅ Підтвердити", f"admin:approve_quest:{part.id}"),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:approve_quest:"))
async def approve_quest(call: CallbackQuery, db: Database, bot: Bot) -> None:
    part_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        part = await session.get(QuestParticipation, part_id)
        if not admin or not part or part.status != "completed":
            await call.answer("Неактуально", show_alert=True)
            return
        user = await session.get(User, part.user_id)
        quest = await session.get(Quest, part.quest_id)
        if not user or not quest:
            return
        quest.xp_reward = normalize_quest_xp(quest.xp_reward, quest.quest_type)
        total, level, leveled = await add_xp(session, user, quest.xp_reward, f"Квест «{quest.title}»", category="quest", created_by=admin.id)
        part.status = "approved"
        part.approved_at = datetime.utcnow()
        await evaluate_automatic_badges(session, user)
        text = f"🏆 Квест <b>{quest.title}</b> підтверджено!\n+{quest.xp_reward} XP\nВсього: {total} XP"
        if leveled:
            text += f"\n🎉 Новий рівень: <b>{level}</b>"
        await _queue_user_notice(session, user, text, source="xp_achievement", title="Квест підтверджено", entity_type="quest", entity_id=quest.id, dedupe_key=f"quest_approved:{quest.id}:{user.id}")
        await session.commit()
        await call.answer("Підтверджено")


# ---------- Badges ----------
@router.callback_query(F.data == "admin:award_badge")
async def badge_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminBadgeAwardState.user_id)
    await call.message.answer("🏅 Вкажіть номер учасника (число).")
    await call.answer()


@router.message(AdminBadgeAwardState.user_id)
async def badge_user(message: Message, state: FSMContext, db: Database) -> None:
    try:
        user_id = int((message.text or "").replace("АМП-", "").replace("AMP-", "").lstrip("0") or "0")
    except ValueError:
        await message.answer("Некоректний номер.")
        return
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        badges = (await session.scalars(select(Badge).where(Badge.active == True).order_by(Badge.id))).all()  # noqa: E712
        if not user:
            await message.answer("Учасника не знайдено.")
            return
        if not badges:
            await message.answer("Немає бейджів у довіднику.")
            await state.clear()
            return
        await state.update_data(user_id=user_id)
        await state.set_state(AdminBadgeAwardState.badge_id)
        text = "Оберіть номер бейджа:\n" + "\n".join(f"<code>{b.id}</code> — {b.icon} {b.name}" for b in badges)
        await message.answer(text)


@router.message(AdminBadgeAwardState.badge_id)
async def badge_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "gamification.manage"):
        await state.clear()
        return
    try:
        badge_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть номер бейджа.")
        return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, data["user_id"])
        badge = await session.get(Badge, badge_id)
        if not admin or not user or not badge:
            await message.answer("Не знайдено.")
            await state.clear()
            return
        existing = await session.scalar(select(UserBadge).where(UserBadge.user_id == user.id, UserBadge.badge_id == badge.id))
        if existing:
            await message.answer("Цей бейдж уже є в учасника.")
            await state.clear()
            return
        session.add(UserBadge(user_id=user.id, badge_id=badge.id, awarded_by=admin.id))
        await _queue_user_notice(session, user, f"🏅 Новий бейдж!\n{badge.icon} <b>{badge.name}</b>\n{badge.description}", source="badge", title="Новий бейдж", entity_type="badge", entity_id=badge.id, dedupe_key=f"manual_badge:{badge.id}:{user.id}")
        await session.commit()
        await message.answer(f"✅ Бейдж {badge.icon} {badge.name} видано {user.full_name}.")
    await state.clear()


# ---------- Rewards ----------
@router.callback_query(F.data == "admin:create_reward")
async def reward_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав для цієї дії", show_alert=True)
            return
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminRewardState.title)
    await call.message.answer("🎁 Назва винагороди?")
    await call.answer()


@router.message(AdminRewardState.title)
async def reward_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminRewardState.description)
    await message.answer("Опис винагороди?")


@router.message(AdminRewardState.description)
async def reward_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminRewardState.min_xp)
    await message.answer("Мінімальний XP для доступу?")


@router.message(AdminRewardState.min_xp)
async def reward_xp(message: Message, state: FSMContext) -> None:
    try:
        min_xp = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть число.")
        return
    await state.update_data(min_xp=min_xp)
    await state.set_state(AdminRewardState.stock)
    await message.answer("Кількість у наявності або <b>безліміт</b>.")


@router.message(AdminRewardState.stock)
async def reward_finish(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "gamification.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip().lower()
    stock = None
    if raw != "безліміт":
        try:
            stock = int(raw)
        except ValueError:
            await message.answer("Вкажіть число або «безліміт».")
            return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            return
        session.add(Reward(title=data["title"], description=data["description"], min_xp=data["min_xp"], stock=stock))
        await session.commit()
    await state.clear()
    await message.answer("✅ Винагороду додано.")


@router.callback_query(F.data == "admin:reward_claims")
async def reward_claims(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        rows = (
            await session.execute(
                select(RewardClaim, User, Reward)
                .join(User, User.id == RewardClaim.user_id)
                .join(Reward, Reward.id == RewardClaim.reward_id)
                .where(RewardClaim.status == "requested")
            )
        ).all()
        if not rows:
            await call.message.answer("🎁 Нових заявок немає.")
        for claim, user, reward in rows:
            await call.message.answer(
                f"🎁 <b>{reward.title}</b>\n👤 {user.full_name}",
                reply_markup=_two_buttons("✅ Видано", f"admin:fulfill_reward:{claim.id}", "↩ Відхилити", f"admin:reject_reward:{claim.id}"),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:fulfill_reward:"))
async def fulfill_reward(call: CallbackQuery, db: Database, bot: Bot) -> None:
    claim_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        claim = await session.get(RewardClaim, claim_id)
        if not admin or not claim or claim.status != "requested":
            await call.answer("Неактуально", show_alert=True)
            return
        reward = await session.get(Reward, claim.reward_id)
        user = await session.get(User, claim.user_id)
        claim.status = "fulfilled"
        claim.fulfilled_at = datetime.utcnow()
        if user and reward:
            await _queue_user_notice(session, user, f"🎁 Винагороду <b>{reward.title}</b> позначено як видану. Дякуємо за активність!", source="reward", title="Винагороду видано", entity_type="reward_claim", entity_id=claim.id, dedupe_key=f"reward_fulfilled:{claim.id}")
        await session.commit()
        await call.answer("Видано")


@router.callback_query(F.data.startswith("admin:reject_reward:"))
async def reject_reward(call: CallbackQuery, db: Database, bot: Bot) -> None:
    claim_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        claim = await session.get(RewardClaim, claim_id)
        if not admin or not claim or claim.status != "requested":
            await call.answer("Неактуально", show_alert=True)
            return
        reward = await session.get(Reward, claim.reward_id)
        user = await session.get(User, claim.user_id)
        claim.status = "rejected"
        if user:
            user.wallet_xp += int(claim.xp_spent or 0)
        if reward and reward.stock is not None:
            reward.stock += 1
        if user and reward:
            await _queue_user_notice(session, user, f"↩ Заявку на <b>{reward.title}</b> відхилено. {claim.xp_spent} XP повернуто у гаманець.", source="reward", title="Заявку на винагороду відхилено", entity_type="reward_claim", entity_id=claim.id, dedupe_key=f"reward_rejected:{claim.id}")
        await session.commit()
        await call.answer("XP повернуто")


# ---------- Activity applications ----------
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


# ---------- Volunteer tasks ----------
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


# ---------- Opportunities ----------
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


# ---------- Broadcast / communication center ----------
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


# ---------- Export ----------
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


# ---------- Role management command ----------
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


# ---------- Moderation (superadmin only) ----------
@router.callback_query(F.data == "admin:moderation")
async def moderation_panel(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            await call.answer("Недостатньо прав для модерації", show_alert=True)
            return
        now = datetime.utcnow()
        active_count = int(await session.scalar(select(func.count(BanRecord.id)).where(BanRecord.lifted_at.is_(None), BanRecord.ends_at > now)) or 0)
    b = InlineKeyboardBuilder()
    b.button(text="⛔ Видати бан", callback_data="admin:ban_new")
    b.button(text=f"🔴 Активні бани ({active_count})", callback_data="admin:ban_active")
    b.button(text="🕘 Історія банів", callback_data="admin:ban_history")
    b.adjust(1)
    await call.message.answer(
        "🛡 <b>Модерація спільноти</b>\n\n"
        "Бан видається конкретному учаснику, має причину та строк. Тут можна скоротити строк, зняти бан і переглянути історію рішень.",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:ban_new")
async def moderation_new_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
    await state.set_state(AdminBanState.user_id)
    await call.message.answer("Введіть <b>АМП-код</b> учасника, якого потрібно тимчасово заблокувати. Наприклад: <code>24</code> або <code>АМП-0024</code>.")
    await call.answer()


@router.message(AdminBanState.user_id)
async def moderation_new_user(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip().upper().replace("АМП-", "").replace("AMP-", "")
    try:
        user_id = int(raw.lstrip("0") or "0")
    except ValueError:
        await message.answer("Не вдалося прочитати АМП-код. Приклад: АМП-0024")
        return
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, user_id)
        if not admin or not user:
            await message.answer("Учасника не знайдено."); return
        if user.role == UserRole.SUPERADMIN.value:
            await message.answer("Суперадміністратора не можна заблокувати."); return
        active = await session.scalar(select(BanRecord).where(BanRecord.user_id == user.id, BanRecord.lifted_at.is_(None), BanRecord.ends_at > datetime.utcnow()))
        if active:
            await message.answer("У цього учасника вже є активний бан. Відкрийте «Активні бани»."); await state.clear(); return
    await state.update_data(user_id=user_id)
    await state.set_state(AdminBanState.days)
    await message.answer(f"👤 <b>{user.full_name}</b>\nНа скільки днів видати бан? Напишіть число від 1 до 365.")


@router.message(AdminBanState.days)
async def moderation_new_days(message: Message, state: FSMContext) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число днів."); return
    if not 1 <= days <= 365:
        await message.answer("Допустимо від 1 до 365 днів."); return
    await state.update_data(days=days)
    await state.set_state(AdminBanState.reason)
    await message.answer("Вкажіть <b>коротку та конкретну причину</b> блокування.")


@router.message(AdminBanState.reason)
async def moderation_new_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    data = await state.get_data()
    reason = (message.text or "").strip()
    if len(reason) < 4:
        await message.answer("Причина занадто коротка. Опишіть порушення конкретніше."); return
    now = datetime.utcnow(); days = int(data["days"]); ends_at = now + timedelta(days=days)
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, int(data["user_id"]))
        if not admin or not user:
            await state.clear(); return
        record = BanRecord(user_id=user.id, issued_by_user_id=admin.id, source="telegram", reason=reason, started_at=now, original_ends_at=ends_at, ends_at=ends_at, updated_at=now)
        session.add(record)
        user.status = UserStatus.BLOCKED.value; user.blocked_until = ends_at; user.block_reason = reason
        await session.flush()
        await log_audit(session, "tg_user_temp_ban", actor_label=admin.full_name, entity_type="ban_record", entity_id=record.id, details=f"АМП-{user.id:04d}; {days} дн.; {reason}")
        await _queue_user_notice(session, user, f"⛔ <b>Ваш профіль тимчасово обмежено</b>\nПричина: {reason}\nСтрок: {days} дн.\nДо: {ends_at.strftime('%d.%m.%Y %H:%M')}", source="moderation", title="Тимчасове обмеження", entity_type="ban_record", entity_id=record.id, dedupe_key=f"ban_notice:{record.id}:issued")
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Бан видано: <b>{user.full_name}</b> до {ends_at.strftime('%d.%m.%Y %H:%M')}.")


@router.callback_query(F.data == "admin:ban_active")
async def moderation_active(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
        rows = (await session.scalars(select(BanRecord).where(BanRecord.lifted_at.is_(None), BanRecord.ends_at > datetime.utcnow()).order_by(BanRecord.ends_at.asc()))).all()
        if not rows:
            await call.message.answer("✅ Активних банів немає."); await call.answer(); return
        for ban in rows[:30]:
            user = await session.get(User, ban.user_id)
            b = InlineKeyboardBuilder()
            b.button(text="⏳ Скоротити", callback_data=f"admin:ban_shorten:{ban.id}")
            b.button(text="✅ Зняти бан", callback_data=f"admin:ban_unban:{ban.id}")
            b.adjust(2)
            await call.message.answer(
                f"⛔ <b>{user.full_name if user else 'Учасник'}</b> • АМП-{ban.user_id:04d}\n"
                f"До: <b>{ban.ends_at.strftime('%d.%m.%Y %H:%M')}</b>\nПричина: {ban.reason}",
                reply_markup=b.as_markup(),
            )
    await call.answer()


@router.callback_query(F.data.startswith("admin:ban_unban:"))
async def moderation_unban_tg(call: CallbackQuery, db: Database, bot: Bot) -> None:
    record_id = int(call.data.rsplit(":", 1)[1]); now = datetime.utcnow()
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        record = await session.get(BanRecord, record_id)
        if not admin or not record or record.lifted_at is not None:
            await call.answer("Запис не знайдено", show_alert=True); return
        user = await session.get(User, record.user_id)
        record.lifted_at = now; record.lift_reason = "Бан знято суперадміністратором у Telegram"; record.updated_at = now
        if user:
            user.status = UserStatus.ACTIVE.value; user.blocked_until = None; user.block_reason = None
        await log_audit(session, "tg_user_unban", actor_label=admin.full_name, entity_type="ban_record", entity_id=record.id, details=record.lift_reason)
        await _queue_user_notice(session, user, "✅ Тимчасове обмеження профілю знято. Ви знову можете користуватися можливостями АМП.", source="moderation", title="Обмеження знято", entity_type="ban_record", entity_id=record.id, dedupe_key=f"ban_notice:{record.id}:lifted")
        await session.commit()
    await call.message.answer("✅ Бан знято.")
    await call.answer()


@router.callback_query(F.data.startswith("admin:ban_shorten:"))
async def moderation_shorten_start_tg(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    record_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
        record = await session.get(BanRecord, record_id)
        if not record or record.lifted_at is not None:
            await call.answer("Бан вже не активний", show_alert=True); return
    await state.update_data(shorten_record_id=record_id)
    await state.set_state(AdminBanState.shorten_days)
    await call.message.answer("На скільки <b>днів від сьогодні</b> залишити бан? Новий строк має бути коротшим за поточний.")
    await call.answer()


@router.message(AdminBanState.shorten_days)
async def moderation_shorten_finish_tg(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "moderation.manage"):
        await state.clear()
        return
    try: days = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число днів."); return
    if not 1 <= days <= 365:
        await message.answer("Допустимо від 1 до 365 днів."); return
    data = await state.get_data(); now = datetime.utcnow(); new_end = now + timedelta(days=days)
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        record = await session.get(BanRecord, int(data["shorten_record_id"]))
        if not admin or not record or record.lifted_at is not None:
            await state.clear(); return
        if new_end >= record.ends_at:
            await message.answer("Новий строк не є коротшим за поточний. Вкажіть меншу кількість днів."); return
        user = await session.get(User, record.user_id)
        record.ends_at = new_end; record.updated_at = now
        if user: user.blocked_until = new_end
        await log_audit(session, "tg_user_ban_shorten", actor_label=admin.full_name, entity_type="ban_record", entity_id=record.id, details=f"Новий строк до {new_end.strftime('%d.%m.%Y %H:%M')}")
        await _queue_user_notice(session, user, f"ℹ️ Строк тимчасового обмеження скорочено. Новий строк: до {new_end.strftime('%d.%m.%Y %H:%M')}.", source="moderation", title="Строк обмеження змінено", entity_type="ban_record", entity_id=record.id)
        await session.commit()
    await state.clear(); await message.answer(f"✅ Строк скорочено до {new_end.strftime('%d.%m.%Y %H:%M')}.")


@router.callback_query(F.data == "admin:ban_history")
async def moderation_history_tg(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав", show_alert=True); return
        rows = (await session.scalars(select(BanRecord).order_by(BanRecord.started_at.desc()).limit(20))).all()
        if not rows:
            await call.message.answer("Історія банів порожня."); await call.answer(); return
        lines = ["🕘 <b>Останні рішення модерації</b>"]
        now = datetime.utcnow()
        for ban in rows:
            user = await session.get(User, ban.user_id)
            if ban.lifted_at: status = f"завершено {ban.lifted_at.strftime('%d.%m.%Y')}"
            elif ban.ends_at <= now: status = "строк минув"
            else: status = f"активний до {ban.ends_at.strftime('%d.%m.%Y')}"
            lines.append(f"\n• АМП-{ban.user_id:04d} {user.full_name if user else ''}\n  {status} • {ban.reason}")
        await call.message.answer("\n".join(lines))
    await call.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Скасовано.")
