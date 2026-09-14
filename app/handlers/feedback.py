from __future__ import annotations

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from ..db import Database
from ..models import Event, EventFeedback, User
from ..reliability import queue_notification, send_notification_now
from ..states import EventFeedbackState

router = Router(name="feedback")


async def _feedback_for_tg(session, feedback_id: int, tg_id: int) -> tuple[EventFeedback | None, Event | None]:
    feedback = await session.get(EventFeedback, feedback_id)
    if not feedback:
        return None, None
    user = await session.get(User, feedback.user_id)
    if not user or user.tg_id != tg_id:
        return None, None
    return feedback, await session.get(Event, feedback.event_id)


async def _send_step(bot: Bot, session, feedback: EventFeedback, user: User, *, ntype: str, body: str, dedupe_suffix: str, button_text: str | None = None, callback_data: str | None = None) -> None:
    row = await queue_notification(
        session,
        user.tg_id,
        body,
        source="event_feedback",
        notification_type="event",
        title="Відгук після події",
        recipient_user_id=user.id,
        entity_type=ntype,
        entity_id=feedback.id,
        dedupe_key=f"event_feedback:{feedback.id}:{dedupe_suffix}",
        button_text=button_text,
        callback_data=callback_data,
    )
    if row:
        await send_notification_now(bot, session, row)


@router.callback_query(F.data.startswith("feedback:rating:"))
async def feedback_rating(call: CallbackQuery, db: Database, bot: Bot, state: FSMContext) -> None:
    try:
        _, _, fid_raw, rating_raw = call.data.split(":")
        fid, rating = int(fid_raw), int(rating_raw)
    except Exception:
        await call.answer("Некоректна відповідь", show_alert=True)
        return
    if rating not in {1, 2, 3, 4, 5}:
        await call.answer("Оберіть оцінку від 1 до 5", show_alert=True)
        return
    async with db.session_factory() as session:
        feedback, event = await _feedback_for_tg(session, fid, call.from_user.id)
        if not feedback:
            await call.answer("Відгук не знайдено", show_alert=True)
            return
        feedback.rating = rating
        feedback.status = "in_progress"
        feedback.updated_at = datetime.utcnow()
        user = await session.get(User, feedback.user_id)
        await _send_step(bot, session, feedback, user, ntype="event_feedback_useful", body=f"⭐ Дякуємо за оцінку події «<b>{event.title if event else 'АМП'}</b>».\n\n<b>Було корисно?</b>", dedupe_suffix="useful")
        await session.commit()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer("Оцінку збережено")


@router.callback_query(F.data.startswith("feedback:yn:"))
async def feedback_yes_no(call: CallbackQuery, db: Database, bot: Bot, state: FSMContext) -> None:
    try:
        _, _, fid_raw, field, value_raw = call.data.split(":")
        fid, value = int(fid_raw), value_raw == "1"
    except Exception:
        await call.answer("Некоректна відповідь", show_alert=True)
        return
    fields = {
        "useful": "useful",
        "knowledge": "new_knowledge",
        "safe": "felt_safe",
        "return": "would_return",
    }
    if field not in fields:
        await call.answer("Некоректна відповідь", show_alert=True)
        return
    async with db.session_factory() as session:
        feedback, event = await _feedback_for_tg(session, fid, call.from_user.id)
        if not feedback:
            await call.answer("Відгук не знайдено", show_alert=True)
            return
        setattr(feedback, fields[field], value)
        feedback.status = "in_progress"
        feedback.updated_at = datetime.utcnow()
        user = await session.get(User, feedback.user_id)
        if field == "useful":
            await _send_step(bot, session, feedback, user, ntype="event_feedback_knowledge", body="🧠 <b>Дізнався/дізналася щось нове?</b>", dedupe_suffix="knowledge")
        elif field == "knowledge":
            await _send_step(bot, session, feedback, user, ntype="event_feedback_safe", body="🛡️ <b>Почувався/почувалася безпечно під час події?</b>", dedupe_suffix="safe")
        elif field == "safe":
            await _send_step(bot, session, feedback, user, ntype="event_feedback_return", body="💙 <b>Хочеш прийти на події АМП ще?</b>", dedupe_suffix="return")
        else:
            await state.set_state(EventFeedbackState.comment)
            await state.update_data(event_feedback_id=feedback.id)
            await _send_step(bot, session, feedback, user, ntype="event_feedback_comment", body="💬 <b>Останнє питання</b>\n\nНапиши короткий коментар про подію одним повідомленням. Якщо не хочеш залишати коментар — натисни «Пропустити».", dedupe_suffix="comment", button_text="Пропустити", callback_data=f"feedback:skip:{feedback.id}")
        await session.commit()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer("Відповідь збережено")


async def _finish_feedback(bot: Bot, session, feedback: EventFeedback, user: User, comment: str = "") -> None:
    feedback.comment = (comment or "").strip()[:3000]
    feedback.status = "completed"
    feedback.completed_at = datetime.utcnow()
    feedback.updated_at = feedback.completed_at
    await _send_step(bot, session, feedback, user, ntype="event_feedback_complete", body="✅ <b>Дякуємо за відгук!</b>\n\nТвоя відповідь допомагає команді АМП покращувати наступні події 💙", dedupe_suffix="complete")


@router.callback_query(F.data.startswith("feedback:skip:"))
async def feedback_skip(call: CallbackQuery, db: Database, bot: Bot, state: FSMContext) -> None:
    fid = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        feedback, _ = await _feedback_for_tg(session, fid, call.from_user.id)
        if not feedback:
            await call.answer("Відгук не знайдено", show_alert=True)
            return
        user = await session.get(User, feedback.user_id)
        await _finish_feedback(bot, session, feedback, user)
        await session.commit()
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer("Дякуємо!")


@router.message(EventFeedbackState.comment)
async def feedback_comment(message: Message, db: Database, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    fid = int(data.get("event_feedback_id") or 0)
    text = (message.text or "").strip()
    if not fid:
        await state.clear()
        return
    async with db.session_factory() as session:
        feedback, _ = await _feedback_for_tg(session, fid, message.from_user.id)
        if not feedback:
            await state.clear()
            await message.answer("Не вдалося знайти форму відгуку.")
            return
        user = await session.get(User, feedback.user_id)
        await _finish_feedback(bot, session, feedback, user, text)
        await session.commit()
    await state.clear()
