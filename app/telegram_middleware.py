from __future__ import annotations

import logging
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from .keyboards import MAIN_MENU_TEXTS
from .model_domains import User
from .observability import log_extra
from .domain_services import get_user_by_tg
from .time_utils import clock

class FSMNavigationMiddleware(BaseMiddleware):
    """Protect multi-step forms from reply-menu text and confirm navigation.

    A reply-keyboard button must never become the answer to the current FSM
    question.  When a form is open, the requested destination is kept inside
    FSM data and the user receives a Yes/No confirmation.  "No" preserves the
    exact form state; "Yes" clears it and opens the requested section.
    """
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            text = (event.text or "").strip()
            state = data.get("state")
            current_state = await state.get_state() if state else None
            if current_state and text in MAIN_MENU_TEXTS:
                await state.update_data(_pending_navigation=text)
                b = InlineKeyboardBuilder()
                b.button(text="✅ Так, перейти", callback_data="fsmnav:yes")
                b.button(text="↩️ Ні, продовжити", callback_data="fsmnav:no")
                b.adjust(1)
                await event.answer(
                    f"⚠️ <b>Ви точно хочете перейти до «{text}»?</b>\n\n"
                    "Незавершена форма залишиться відкритою, якщо обрати «Ні». "
                    "Якщо обрати «Так» — поточне заповнення буде скасовано.",
                    reply_markup=b.as_markup(),
                )
                return None
            is_command = text.startswith(("/start", "/menu", "/smart", "/help", "/myqr", "/invite", "/cancel"))
            if current_state and is_command:
                await state.clear()
        return await handler(event, data)

class TemporaryBanMiddleware(BaseMiddleware):
    """Block Telegram interactions for temporarily/permanently blocked profiles.

    /start and /help remain available so a user can see their restriction and
    contact information; expired temporary bans are automatically cleared by
    get_user_by_tg().
    """
    async def __call__(self, handler, event, data):
        db = data.get("db")
        from_user = getattr(event, "from_user", None)
        if not db or not from_user:
            return await handler(event, data)
        async with db.session_factory() as session:
            user = await get_user_by_tg(session, from_user.id)
        if not user or user.status != "blocked":
            return await handler(event, data)

        if isinstance(event, Message):
            text = (event.text or "").strip().lower()
            if text.startswith("/start") or text.startswith("/help"):
                return await handler(event, data)
            until = f" до {user.blocked_until.strftime('%d.%m.%Y %H:%M')}" if user.blocked_until else ""
            reason = f"\nПричина: {user.block_reason}" if user.block_reason else ""
            await event.answer(f"⛔ Доступ до функцій АМП тимчасово обмежено{until}.{reason}")
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔ Доступ тимчасово обмежено. Відкрийте /start для деталей.", show_alert=True)
        return None

class DeletedAccountMiddleware(BaseMiddleware):
    """Hard-gate soft-deleted participant profiles while preserving /start restoration flow."""
    async def __call__(self, handler, event, data):
        db=data.get("db"); from_user=getattr(event,"from_user",None)
        if not db or not from_user:
            return await handler(event,data)
        async with db.session_factory() as session:
            user=await get_user_by_tg(session,from_user.id)
        if not user or user.status not in {"deleted","deleted_permanent"}:
            return await handler(event,data)
        state=data.get("state")
        current_state=await state.get_state() if state else None
        if current_state and current_state.startswith("RestorationState:") and user.status=="deleted":
            return await handler(event,data)
        if isinstance(event,Message):
            text=(event.text or "").strip().lower()
            if text.startswith("/start"):
                return await handler(event,data)
            await event.answer("🗑 Доступ до функцій закрито. Відкрийте /start для інформації про статус акаунта та можливість відновлення.")
        elif isinstance(event,CallbackQuery):
            if user.status=="deleted" and (event.data or "").startswith("restore:"):
                return await handler(event,data)
            await event.answer("Доступ до цього акаунта закрито. Відкрийте /start.",show_alert=True)
        return None

class LastActivityMiddleware(BaseMiddleware):
    """Persist the latest Telegram interaction for communication targeting."""
    async def __call__(self, handler, event, data):
        db = data.get("db")
        from_user = getattr(event, "from_user", None)
        if db and from_user:
            try:
                async with db.session_factory() as session:
                    user = await session.scalar(select(User).where(User.tg_id == from_user.id))
                    if user and user.status == "active":
                        user.last_activity_at = clock.storage_utc()
                        await session.commit()
            except Exception as exc:
                logging.getLogger("amp.activity").exception(
                    "Не вдалося оновити last_activity_at",
                    extra=log_extra("LAST_ACTIVITY_UPDATE_FAILED", tg_id=getattr(from_user, "id", None), exception_type=type(exc).__name__),
                )
        return await handler(event, data)
