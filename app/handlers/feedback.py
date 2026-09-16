from __future__ import annotations

from ..time_utils import clock

from datetime import datetime
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..db import Database
from ..models import Event, EventFeedback, User
from ..states import EventFeedbackState
from ..observability import log_extra

router = Router(name="feedback")


def _rating_keyboard(fid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(value), callback_data=f"feedback:rating:{fid}:{value}") for value in range(1, 6)
    ]])


def _yes_no_keyboard(fid: int, field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так", callback_data=f"feedback:yn:{fid}:{field}:1"),
        InlineKeyboardButton(text="❌ Ні", callback_data=f"feedback:yn:{fid}:{field}:0"),
    ]])


def _completed_keyboard(fid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💬 Додати коментар", callback_data=f"feedback:comment:{fid}")
    ]])


async def _feedback_for_tg(session, feedback_id: int, tg_id: int) -> tuple[EventFeedback | None, Event | None]:
    feedback = await session.get(EventFeedback, feedback_id)
    if not feedback:
        return None, None
    user = await session.get(User, feedback.user_id)
    if not user or user.tg_id != tg_id:
        return None, None
    return feedback, await session.get(Event, feedback.event_id)


async def _replace_question(call: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Keep micro-feedback in one Telegram message instead of sending a chain."""
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:
        await call.message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("feedback:rating:"))
async def feedback_rating(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        _, _, fid_raw, rating_raw = call.data.split(":")
        fid, rating = int(fid_raw), int(rating_raw)
    except Exception:
        await call.answer("Некоректна відповідь", show_alert=True); return
    if rating not in {1, 2, 3, 4, 5}:
        await call.answer("Оберіть оцінку від 1 до 5", show_alert=True); return
    async with db.session_factory() as session:
        feedback, event = await _feedback_for_tg(session, fid, call.from_user.id)
        if not feedback:
            await call.answer("Відгук не знайдено", show_alert=True); return
        if feedback.status == "completed":
            await call.answer("Відгук уже завершено", show_alert=True); return
        feedback.rating = rating
        feedback.status = "in_progress"
        feedback.updated_at = clock.storage_utc()
        await session.commit()
    await _replace_question(
        call,
        f"⭐ <b>{event.title if event else 'Подія АМП'}</b> · оцінка <b>{rating}/5</b>\n\n👍 <b>Було корисно?</b>",
        _yes_no_keyboard(fid, "useful"),
    )
    await call.answer("Збережено")


@router.callback_query(F.data.startswith("feedback:yn:"))
async def feedback_yes_no(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        _, _, fid_raw, field, value_raw = call.data.split(":")
        fid, value = int(fid_raw), value_raw == "1"
    except Exception:
        await call.answer("Некоректна відповідь", show_alert=True); return
    fields = {"useful": "useful", "knowledge": "new_knowledge", "safe": "felt_safe", "return": "would_return"}
    if field not in fields:
        await call.answer("Некоректна відповідь", show_alert=True); return
    async with db.session_factory() as session:
        feedback, event = await _feedback_for_tg(session, fid, call.from_user.id)
        if not feedback:
            await call.answer("Відгук не знайдено", show_alert=True); return
        if feedback.status == "completed":
            await call.answer("Відгук уже завершено", show_alert=True); return
        setattr(feedback, fields[field], value)
        feedback.status = "in_progress"
        feedback.updated_at = clock.storage_utc()
        if field == "return":
            feedback.status = "completed"
            feedback.completed_at = clock.storage_utc()
        await session.commit()

    if field == "useful":
        await _replace_question(call, "🧠 <b>Дізнався/дізналася щось нове?</b>", _yes_no_keyboard(fid, "knowledge"))
    elif field == "knowledge":
        await _replace_question(call, "🛡️ <b>Почувався/почувалася безпечно під час події?</b>", _yes_no_keyboard(fid, "safe"))
    elif field == "safe":
        await _replace_question(call, "💙 <b>Хочеш прийти на події АМП ще?</b>", _yes_no_keyboard(fid, "return"))
    else:
        await state.clear()
        await _replace_question(
            call,
            "✅ <b>Дякуємо!</b> Відгук збережено.\n\nЦе зайняло кілька натискань і допоможе команді АМП покращувати наступні події. Коментар — необов’язковий.",
            _completed_keyboard(fid),
        )
    await call.answer("Збережено")


@router.callback_query(F.data.startswith("feedback:comment:"))
async def feedback_comment_start(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        fid = int(call.data.rsplit(":", 1)[1])
    except ValueError:
        await call.answer("Некоректний відгук", show_alert=True); return
    async with db.session_factory() as session:
        feedback, _ = await _feedback_for_tg(session, fid, call.from_user.id)
        if not feedback:
            await call.answer("Відгук не знайдено", show_alert=True); return
    await state.set_state(EventFeedbackState.comment)
    await state.update_data(event_feedback_id=fid)
    await call.message.answer("💬 Напиши короткий коментар одним повідомленням. Щоб скасувати — /cancel.")
    await call.answer()


# Backward-compatible old skip callback from v1.9/v1.10 messages. The core
# micro-feedback is already complete before an optional comment is requested.
@router.callback_query(F.data.startswith("feedback:skip:"))
async def feedback_skip(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    try:
        fid = int(call.data.rsplit(":", 1)[1])
    except ValueError:
        await call.answer("Некоректний відгук", show_alert=True); return
    async with db.session_factory() as session:
        feedback, _ = await _feedback_for_tg(session, fid, call.from_user.id)
        if feedback and feedback.status != "completed":
            feedback.status = "completed"
            feedback.completed_at = clock.storage_utc()
            feedback.updated_at = feedback.completed_at
            await session.commit()
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logging.getLogger("amp.feedback").debug(
            "Не вдалося прибрати feedback markup",
            extra=log_extra("TG_FEEDBACK_MARKUP_CLEAR_FAILED", tg_id=call.from_user.id, exception_type=type(exc).__name__),
        )
    await call.answer("Дякуємо!")


@router.message(EventFeedbackState.comment)
async def feedback_comment(message: Message, db: Database, state: FSMContext) -> None:
    data = await state.get_data()
    fid = int(data.get("event_feedback_id") or 0)
    text = (message.text or "").strip()
    if not fid:
        await state.clear(); return
    if not text:
        await message.answer("Напиши хоча б кілька слів або /cancel."); return
    async with db.session_factory() as session:
        feedback, _ = await _feedback_for_tg(session, fid, message.from_user.id)
        if not feedback:
            await state.clear(); await message.answer("Не вдалося знайти форму відгуку."); return
        feedback.comment = text[:3000]
        feedback.status = "completed"
        feedback.completed_at = feedback.completed_at or clock.storage_utc()
        feedback.updated_at = clock.storage_utc()
        await session.commit()
    await state.clear()
    await message.answer("💙 Дякуємо за коментар!")
