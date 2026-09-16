from __future__ import annotations

from ..observability import log_extra
from ..time_utils import clock

from datetime import datetime
import logging
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from ..config import Settings
from ..db import Database
from ..keyboards import event_detail_keyboard, event_waitlist_offer_keyboard, events_keyboard
from ..media import telegram_photo_input
from ..models import Event, EventRegistration, UserStatus
from ..services import accept_event_reservation, get_user_by_tg, join_event_waitlist, process_event_operations, register_for_event
from ..ui_labels import lifecycle_status_label
from ..engagement import process_expired_content
from ..content_views import content_view_stat, record_content_view

router = Router(name="events")


async def _send_events(target, db: Database) -> None:
    async with db.session_factory() as session:
        changed = await process_expired_content(session)
        if changed: await session.commit()
        events = (await session.scalars(
            select(Event).where(Event.status.in_(["open", "closed", "postponed"]), Event.starts_at >= clock.local_wall()).order_by(Event.starts_at.asc()).limit(20)
        )).all()
        if not events:
            await target.answer("📅 Найближчих відкритих подій поки немає.")
            return
        lines=["📅 <b>Найближчі події АМП</b>","","<b>Оберіть подію:</b>"]
        for idx,event in enumerate(events,start=1):
            status_note = "" if event.status == "open" else (" • 🔒 реєстрацію закрито" if event.status == "closed" else " • 📅 перенесено")
            lines.append(f"\n<b>{idx}. {escape(event.title)}</b>\n🕒 {event.starts_at.strftime('%d.%m.%Y %H:%M')} • 📍 {escape(event.location or 'АМП')}{status_note}")
        await target.answer("\n".join(lines),reply_markup=events_keyboard(events))


@router.message(F.text == "📅 Події")
async def list_events(message: Message, db: Database) -> None:
    await _send_events(message, db)


@router.callback_query(F.data == "nav:events")
async def nav_events(call: CallbackQuery, db: Database) -> None:
    await _send_events(call.message, db)
    await call.answer()


@router.callback_query(F.data.regexp(r"^event:\d+$"))
async def event_detail(call: CallbackQuery, db: Database, settings: Settings) -> None:
    try:
        event_id = int(call.data.split(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await call.answer("Некоректна подія", show_alert=True)
        return

    async with db.session_factory() as session:
        # Opening a card must not be blocked by an unrelated lifecycle job.
        # A scheduler regression used to make event buttons appear dead because
        # this call raised before the detail card was rendered.
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

        reg = await session.scalar(
            select(EventRegistration).where(EventRegistration.event_id == event.id, EventRegistration.user_id == user.id)
        )
        await record_content_view(session, "event", event.id, user=user)
        await session.flush()
        view_stat = await content_view_stat(session, "event", event.id)
        await session.commit()

        date_text = event.starts_at.strftime("%d.%m.%Y %H:%M")
        safe_title = escape(event.title or "Подія")
        safe_location = escape(event.location or "АМП")
        safe_description = escape(event.description or "Без додаткового опису.")
        text = (
            f"📅 <b>{safe_title}</b>\n"
            f"🕒 {date_text}\n"
            f"📍 {safe_location}\n"
            f"📌 Статус: {escape(lifecycle_status_label(event.status))}\n"
            f"⚡ {event.xp_reward} XP\n"
            f"⏱ {event.volunteer_hours:g} волонтерських годин\n"
            f"👁 Переглядів: <b>{view_stat['views']}</b>\n\n"
            f"{safe_description}"
        )
        photo = await telegram_photo_input(db, event.image_path)
        registered = bool(reg and reg.status != "cancelled")
        keyboard = None
        public_url = f"{settings.public_base_url}/event/{event.share_token}" if event.share_token else ""
        share_button_url = ""
        if public_url:
            share_button_url = (
                "https://t.me/share/url?url=" + quote(public_url, safe="") +
                "&text=" + quote(f"Подія АМП: {event.title}", safe="")
            )
        if clock.event_utc(event.starts_at) >= clock.now_utc():
            if event.status in {"open", "postponed"}:
                keyboard = event_detail_keyboard(event.id, registered, share_button_url, reg.status if reg else None)
            elif event.status == "closed" and registered:
                keyboard = event_detail_keyboard(event.id, True, share_button_url, reg.status if reg else None)

        # Telegram media captions are substantially shorter than ordinary
        # messages.  Long event descriptions used to make the callback fail
        # silently for cards with a photo.
        if photo and len(text) <= 950:
            await call.message.answer_photo(photo, caption=text, reply_markup=keyboard)
        elif photo:
            await call.message.answer_photo(
                photo,
                caption=f"📅 <b>{safe_title}</b>\n🕒 {date_text}\n👁 {view_stat['views']} переглядів",
            )
            await call.message.answer(text, reply_markup=keyboard)
        else:
            await call.message.answer(text, reply_markup=keyboard)
        await call.answer()


@router.callback_query(F.data.startswith("event_join:"))
async def event_join(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await call.answer("Профіль не активований", show_alert=True)
            return
        event = await session.get(Event, event_id)
        if not event or event.status not in {"open", "postponed"} or clock.event_utc(event.starts_at) < clock.now_utc():
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
        await call.message.answer(f"✅ Реєстрацію на <b>{event.title}</b> підтверджено.")
        await call.answer()


@router.callback_query(F.data.startswith("event_waitlist:"))
async def event_waitlist(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not user or user.status != UserStatus.ACTIVE.value or not event or event.status not in {"open", "postponed"}:
            await call.answer("Черга недоступна", show_alert=True)
            return
        if not event.capacity:
            await register_for_event(session, user.id, event.id)
            await session.commit()
            await call.message.answer(f"✅ Реєстрацію на <b>{event.title}</b> підтверджено.")
            await call.answer()
            return
        count = int(await session.scalar(select(func.count(EventRegistration.id)).where(
            EventRegistration.event_id == event.id,
            EventRegistration.status.in_(["registered", "reserved", "checked_in", "attended"]),
        )) or 0)
        if count < event.capacity:
            await register_for_event(session, user.id, event.id)
            await session.commit()
            await call.message.answer(f"🎉 Місце вже вільне — тебе одразу зареєстровано на <b>{event.title}</b>.")
            await call.answer()
            return
        reg = await join_event_waitlist(session, user.id, event.id)
        await session.commit()
        await call.message.answer(f"⏳ Тебе додано в чергу на <b>{event.title}</b>.\n\nЯк тільки звільниться місце, бот автоматично повідомить і зарезервує його для тебе на 2 години.")
        await call.answer("Додано в чергу")


@router.callback_query(F.data.startswith("event_reserve_accept:"))
async def event_reserve_accept(call: CallbackQuery, db: Database) -> None:
    event_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        event = await session.get(Event, event_id)
        if not user or not event:
            await call.answer("Не знайдено", show_alert=True)
            return
        reg, state = await accept_event_reservation(session, user.id, event.id)
        if state == "accepted":
            await session.commit()
            await call.message.answer(f"✅ Місце підтверджено. Ти зареєстрований/а на <b>{event.title}</b>.")
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
        reg = await session.scalar(
            select(EventRegistration).where(EventRegistration.event_id == event_id, EventRegistration.user_id == user.id)
        )
        if reg and reg.status in {"registered", "reserved", "waitlisted", "checked_in"}:
            previous = reg.status
            reg.status = "cancelled"
            reg.checkin_at = None
            reg.reservation_expires_at = None
            await process_event_operations(session)
            await session.commit()
            await call.message.answer("❌ " + ("Тебе прибрано з черги." if previous == "waitlisted" else "Реєстрацію скасовано. Історія участі збережена."))
        else:
            await call.message.answer("ℹ️ Цю реєстрацію вже не можна скасувати.")
        await call.answer()
