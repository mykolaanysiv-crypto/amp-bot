from __future__ import annotations

from ..observability import log_extra
from ..time_utils import clock

from io import BytesIO
import logging
from html import escape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select
import qrcode

from ..ambassadors import AMP_TEAM_ROLES
from ..config import Settings
from ..db import Database
from ..keyboards import event_detail_keyboard, event_waitlist_offer_keyboard, events_keyboard
from ..media import telegram_photo_input
from ..model_domains import Event, EventRegistration, UserStatus
from ..domain_services import accept_event_reservation, get_user_by_tg, join_event_waitlist, process_event_operations, register_for_event
from ..ui_labels import lifecycle_status_label
from ..engagement import process_expired_content
from ..content_views import content_view_stat, record_content_view
from ..event_schedule import event_end_local

router = Router(name="events")


def _event_scope(event: Event) -> str:
    return getattr(event, "access_scope", "general") or "general"


def _can_access_event(user, event: Event) -> bool:
    return _event_scope(event) != "team" or bool(user and user.status == UserStatus.ACTIVE.value and user.role in AMP_TEAM_ROLES)


def _event_commitment_lines(event: Event) -> str:
    lines = [f"⚡ За фактичну участь: <b>+{int(event.xp_reward or 0)} XP</b>"]
    bonus = int(getattr(event, "preregistration_bonus_xp", 0) or 0)
    penalty = int(getattr(event, "no_show_penalty_xp", 0) or 0)
    if bonus:
        lines.append(f"🎟 За попередню реєстрацію + участь: <b>+{bonus} XP</b>")
    if penalty:
        lines.append(f"🚫 Неявка без скасування до початку: <b>-{penalty} XP</b>")
    return "\n".join(lines)


def _registration_success_text(event: Event, prefix: str = "✅ Реєстрацію підтверджено.") -> str:
    return (
        f"{prefix}\n\n{_event_commitment_lines(event)}\n\n"
        f"Якщо плани зміняться — скасуй реєстрацію <b>до {event.starts_at.strftime('%d.%m.%Y %H:%M')}</b>. "
        "Так місце зможе отримати інший учасник, а штраф за неявку не застосовуватиметься."
    )


def _event_hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Загальні події", callback_data="nav:events:general")],
        [InlineKeyboardButton(text="🧭 Події для АМПасадорів", callback_data="nav:events:team")],
    ])


async def _send_events(target, db: Database, *, scope: str, tg_id: int) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
        if scope == "team" and (not user or user.status != UserStatus.ACTIVE.value or user.role not in AMP_TEAM_ROLES):
            await target.answer("🔒 Події для АМПасадорів доступні лише команді АМП.")
            return
        changed = await process_expired_content(session)
        if changed:
            await session.commit()
        events = (await session.scalars(
            select(Event).where(
                Event.status.in_(["open", "closed", "postponed"]),
                or_(Event.ends_at.is_(None), Event.ends_at >= clock.local_wall()),
                Event.access_scope == scope,
            ).order_by(Event.starts_at.asc()).limit(20)
        )).all()
        if not events:
            label = "подій для команди АМП" if scope == "team" else "загальних подій"
            await target.answer(f"📅 Найближчих {label} поки немає.")
            return
        title = "🧭 <b>Події для АМПасадорів</b>" if scope == "team" else "🌍 <b>Загальні події АМП</b>"
        lines=[title, "", "<b>Оберіть подію:</b>"]
        for idx,event in enumerate(events,start=1):
            status_note = "" if event.status == "open" else (" • 🔒 реєстрацію закрито" if event.status == "closed" else " • 📅 перенесено")
            lines.append(f"\n<b>{idx}. {escape(event.title)}</b>\n🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')} — {event_end_local(event).strftime('%d.%m.%Y %H:%M')} • 📍 {escape(event.location or 'АМП')}{status_note}")
        await target.answer("\n".join(lines),reply_markup=events_keyboard(events))


async def _open_events_hub(target, db: Database, tg_id: int) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
    if user and user.status == UserStatus.ACTIVE.value and user.role in AMP_TEAM_ROLES:
        await target.answer("📅 <b>Події</b>\n\nОбери категорію:", reply_markup=_event_hub_keyboard())
    else:
        await _send_events(target, db, scope="general", tg_id=tg_id)


@router.message(F.text == "📅 Події")
async def list_events(message: Message, db: Database) -> None:
    await _open_events_hub(message, db, message.from_user.id)


@router.callback_query(F.data == "nav:events")
async def nav_events(call: CallbackQuery, db: Database) -> None:
    await _open_events_hub(call.message, db, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "nav:events:general")
async def nav_events_general(call: CallbackQuery, db: Database) -> None:
    await _send_events(call.message, db, scope="general", tg_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "nav:events:team")
async def nav_events_team(call: CallbackQuery, db: Database) -> None:
    await _send_events(call.message, db, scope="team", tg_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data.regexp(r"^event:\d+$"))
async def event_detail(call: CallbackQuery, db: Database, settings: Settings) -> None:
    try:
        event_id = int(call.data.split(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await call.answer("Некоректна подія", show_alert=True)
        return

    async with db.session_factory() as session:
        try:
            changed = await process_expired_content(session)
            if changed:
                await session.commit()
        except Exception as exc:
            await session.rollback()
            logging.getLogger("amp.events").exception(
                "Lifecycle refresh failed while opening event %s", event_id,
                extra=log_extra("EVENT_LIFECYCLE_REFRESH_FAILED", entity_type="event", entity_id=event_id, exception_type=type(exc).__name__),
            )

        user = await get_user_by_tg(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not user or not event:
            await call.answer("Не знайдено", show_alert=True)
            return
        if not _can_access_event(user, event):
            await call.answer("Ця подія доступна лише команді АМП", show_alert=True)
            return

        reg = await session.scalar(
            select(EventRegistration).where(EventRegistration.event_id == event.id, EventRegistration.user_id == user.id)
        )
        await record_content_view(session, "event", event.id, user=user)
        await session.flush()
        view_stat = await content_view_stat(session, "event", event.id)
        await session.commit()

        date_text = f"{event.starts_at.strftime('%d.%m.%Y %H:%M')} — {event_end_local(event).strftime('%d.%m.%Y %H:%M')}"
        safe_title = escape(event.title or "Подія")
        safe_location = escape(event.location or "АМП")
        safe_description = escape(event.description or "Без додаткового опису.")
        scope_line = "🧭 Лише для команди АМП\n" if _event_scope(event) == "team" else ""
        text = (
            f"📅 <b>{safe_title}</b>\n"
            f"{scope_line}"
            f"🕒 {date_text}\n"
            f"📍 {safe_location}\n"
            f"📌 Статус: {escape(lifecycle_status_label(event.status))}\n"
            f"{_event_commitment_lines(event)}\n"
            f"⏱ {event.volunteer_hours:g} волонтерських годин\n"
            f"👁 Переглядів: <b>{view_stat['views']}</b>\n\n"
            f"{safe_description}"
        )
        photo = await telegram_photo_input(db, event.image_path)
        registered = bool(reg and reg.status != "cancelled")
        keyboard = None
        public_url = f"{settings.public_base_url}/event/{event.share_token}" if event.share_token and _event_scope(event) == "general" else ""
        share_button_url = ""
        if public_url:
            share_button_url = (
                "https://t.me/share/url?url=" + quote(public_url, safe="") +
                "&text=" + quote(f"Подія АМП: {event.title}", safe="")
            )
        back_callback = "nav:events:team" if _event_scope(event) == "team" else "nav:events:general"
        if clock.event_utc(event.starts_at) >= clock.now_utc():
            if event.status in {"open", "postponed"}:
                keyboard = event_detail_keyboard(event.id, registered, share_button_url, reg.status if reg else None, ambassador_qr=(user.role in AMP_TEAM_ROLES and registered), back_callback=back_callback)
            elif event.status == "closed" and registered:
                keyboard = event_detail_keyboard(event.id, True, share_button_url, reg.status if reg else None, ambassador_qr=(user.role in AMP_TEAM_ROLES), back_callback=back_callback)

        if photo and len(text) <= 950:
            await call.message.answer_photo(photo, caption=text, reply_markup=keyboard)
        elif photo:
            await call.message.answer_photo(photo, caption=f"📅 <b>{safe_title}</b>\n🕒 {date_text}\n👁 {view_stat['views']} переглядів")
            await call.message.answer(text, reply_markup=keyboard)
        else:
            await call.message.answer(text, reply_markup=keyboard)
        await call.answer()


@router.callback_query(F.data.startswith("ambassador:event_qr:"))
async def ambassador_event_qr(call: CallbackQuery, db: Database, bot: Bot) -> None:
    event_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        event = await session.get(Event, event_id)
        reg = await session.scalar(select(EventRegistration).where(
            EventRegistration.event_id == event_id, EventRegistration.user_id == user.id if user else -1
        )) if user else None
        if (not user or user.role not in AMP_TEAM_ROLES or not event or not reg
                or reg.status not in {"registered", "checked_in", "attended"}):
            await call.answer("QR доступний зареєстрованим членам команди АМП", show_alert=True)
            return
    username = (await bot.get_me()).username
    deep_link = f"https://t.me/{username}?start=checkin_{event.checkin_token}"
    qr = qrcode.QRCode(version=None, box_size=12, border=3)
    qr.add_data(deep_link); qr.make(fit=True)
    image = qr.make_image(fill_color="#0B5B6C", back_color="white").convert("RGB")
    bio = BytesIO(); image.save(bio, format="PNG")
    await call.message.answer_document(
        BufferedInputFile(bio.getvalue(), filename=f"AMP_event_{event.id}_QR.png"),
        caption=(f"🔳 <b>QR-код події</b>\n<b>{escape(event.title)}</b>\n🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                 "Покажіть цей QR учасникам для відмітки на події. Фінальне нарахування XP/годин залишається під контролем системи та підтвердження участі."),
    )
    await call.answer("QR згенеровано")


@router.callback_query(F.data.startswith("event_join:"))
async def event_join(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await call.answer("Профіль не активований", show_alert=True)
            return
        event = await session.get(Event, event_id)
        if not event or not _can_access_event(user, event) or event.status not in {"open", "postponed"} or clock.event_utc(event.starts_at) < clock.now_utc():
            await call.answer("Реєстрація недоступна", show_alert=True)
            return
        if event.capacity:
            count = await session.scalar(
                select(func.count(EventRegistration.id)).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.status.in_(["registered", "reserved", "checked_in", "attended"]),
                )
            )
            if (count or 0) >= event.capacity:
                await call.message.answer(
                    "⚠️ <b>Місць наразі немає.</b>\n\nХочеш стати в чергу? Якщо місце звільниться, воно буде автоматично зарезервоване для тебе на 2 години.",
                    reply_markup=event_waitlist_offer_keyboard(event.id),
                )
                await call.answer("Подія заповнена")
                return
        await register_for_event(session, user.id, event.id)
        await session.commit()
        await call.message.answer(f"✅ <b>{event.title}</b>\n\n" + _registration_success_text(event))
        await call.answer()


@router.callback_query(F.data.startswith("event_waitlist:"))
async def event_waitlist(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not user or user.status != UserStatus.ACTIVE.value or not event or not _can_access_event(user, event) or event.status not in {"open", "postponed"}:
            await call.answer("Черга недоступна", show_alert=True)
            return
        if not event.capacity:
            await register_for_event(session, user.id, event.id)
            await session.commit()
            await call.message.answer(f"✅ <b>{event.title}</b>\n\n" + _registration_success_text(event))
            await call.answer()
            return
        count = int(await session.scalar(select(func.count(EventRegistration.id)).where(
            EventRegistration.event_id == event.id,
            EventRegistration.status.in_(["registered", "reserved", "checked_in", "attended"]),
        )) or 0)
        if count < event.capacity:
            await register_for_event(session, user.id, event.id)
            await session.commit()
            await call.message.answer(f"🎉 Місце вже вільне — тебе одразу зареєстровано на <b>{event.title}</b>.\n\n" + _registration_success_text(event, "✅ Місце підтверджено."))
            await call.answer()
            return
        await join_event_waitlist(session, user.id, event.id)
        await session.commit()
        await call.message.answer(f"⏳ Тебе додано в чергу на <b>{event.title}</b>.\n\nЯк тільки звільниться місце, бот автоматично повідомить і зарезервує його для тебе на 2 години.")
        await call.answer("Додано в чергу")


@router.callback_query(F.data.startswith("event_reserve_accept:"))
async def event_reserve_accept(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not user or not event or not _can_access_event(user, event):
            await call.answer("Не знайдено", show_alert=True)
            return
        reg, state = await accept_event_reservation(session, user.id, event.id)
        if state == "accepted":
            await session.commit()
            await call.message.answer(f"✅ Ти зареєстрований/а на <b>{event.title}</b>.\n\n" + _registration_success_text(event, "✅ Місце з черги підтверджено."))
            await call.answer("Місце підтверджено")
            return
        if state == "expired":
            await process_event_operations(session)
            await session.commit()
            await call.message.answer("⌛ Двогодинний резерв уже завершився. Тебе повернуто в чергу; про наступне вільне місце бот повідомить автоматично.")
            await call.answer("Резерв завершився", show_alert=True)
            return
        await call.answer("Активного резерву немає", show_alert=True)


@router.callback_query(F.data.startswith("event_cancel:"))
async def event_cancel(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            return
        event = await session.get(Event, event_id)
        if not event or not _can_access_event(user, event):
            await call.answer("Недоступно", show_alert=True)
            return
        reg = await session.scalar(
            select(EventRegistration).where(EventRegistration.event_id == event_id, EventRegistration.user_id == user.id)
        )
        if reg and reg.status in {"registered", "reserved", "waitlisted", "checked_in"}:
            previous = reg.status
            event_started = bool(clock.event_utc(event.starts_at) and clock.event_utc(event.starts_at) <= clock.now_utc())
            if previous != "waitlisted" and event_started:
                penalty = int(getattr(event, "no_show_penalty_xp", 0) or 0)
                warning = (f" Якщо після завершення буде статус «Не прийшов», система спише {penalty} XP." if penalty else "")
                await call.answer("Після початку події скасування недоступне", show_alert=True)
                await call.message.answer(
                    "⛔ <b>Подія вже почалася.</b>\n\n"
                    "Самостійно скасувати реєстрацію можна лише до початку події." + warning +
                    "\nЯкщо статус потрібно виправити через помилку — звернися до команди АМП."
                )
                return
            reg.status = "cancelled"
            reg.checkin_at = None
            reg.reservation_expires_at = None
            await process_event_operations(session)
            await session.commit()
            await call.message.answer("❌ " + ("Тебе прибрано з черги." if previous == "waitlisted" else "Реєстрацію скасовано вчасно. Штраф за неявку не застосовуватиметься."))
        else:
            await call.message.answer("ℹ️ Цю реєстрацію вже не можна скасувати.")
        await call.answer()
