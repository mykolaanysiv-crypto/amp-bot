from __future__ import annotations

from datetime import datetime
import logging
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from ..db import Database
from ..keyboards import quest_detail_keyboard, quests_keyboard
from ..media import telegram_photo_input
from ..models import Quest, QuestParticipation, UserStatus
from ..services import get_user_by_tg
from ..engagement import process_expired_content
from ..content_views import content_view_stat, record_content_view

router = Router(name="quests")


async def _send_quests(target, db: Database) -> None:
    async with db.session_factory() as session:
        changed=await process_expired_content(session)
        if changed: await session.commit()
        quests=(await session.scalars(select(Quest).where(Quest.active == True, Quest.status.in_(["open","postponed"])).where((Quest.ends_at.is_(None)) | (Quest.ends_at >= datetime.now())).order_by(Quest.ends_at.asc()).limit(20))).all()  # noqa: E712
        if not quests:
            await target.answer("🎯 Активних квестів зараз немає.")
            return
        lines=["🎯 <b>Активні квести</b>","","<b>Оберіть квест:</b>"]
        for idx,quest in enumerate(quests,start=1):
            deadline=quest.ends_at.strftime("%d.%m.%Y %H:%M") if quest.ends_at else "без дедлайну"
            lines.append(f"\n<b>{idx}. {escape(quest.title)}</b>\n⚡ {quest.xp_reward} XP • 📆 {deadline}")
        await target.answer("\n".join(lines),reply_markup=quests_keyboard(quests))


@router.message(F.text == "🎯 Квести")
async def list_quests(message: Message, db: Database) -> None:
    await _send_quests(message, db)


@router.callback_query(F.data == "nav:quests")
async def nav_quests(call: CallbackQuery, db: Database) -> None:
    await _send_quests(call.message, db)
    await call.answer()


@router.callback_query(F.data.regexp(r"^quest:\d+$"))
async def quest_detail(call: CallbackQuery, db: Database) -> None:
    try:
        quest_id = int(call.data.split(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await call.answer("Некоректний квест", show_alert=True)
        return
    async with db.session_factory() as session:
        try:
            changed = await process_expired_content(session)
            if changed:
                await session.commit()
        except Exception:
            await session.rollback()
            logging.getLogger("amp.quests").exception("Lifecycle refresh failed while opening quest %s", quest_id)
        user = await get_user_by_tg(session, call.from_user.id)
        quest = await session.get(Quest, quest_id)
        if not user or not quest:
            await call.answer("Не знайдено", show_alert=True)
            return
        part = await session.scalar(
            select(QuestParticipation).where(QuestParticipation.quest_id == quest.id, QuestParticipation.user_id == user.id)
        )
        await record_content_view(session, "quest", quest.id, user=user)
        await session.flush()
        view_stat = await content_view_stat(session, "quest", quest.id)
        await session.commit()
        deadline = quest.ends_at.strftime("%d.%m.%Y") if quest.ends_at else "без дедлайну"
        progress = ""
        if quest.quest_type == "team":
            progress = f"\n👥 Командний прогрес: <b>{quest.progress_value}/{quest.target_value}</b>"
        safe_title = escape(quest.title or "Квест")
        safe_description = escape(quest.description or "Без додаткового опису.")
        text = (
            f"{'👥' if quest.quest_type == 'team' else '🎯'} <b>{safe_title}</b>\n"
            f"⚡ Нагорода: {quest.xp_reward} XP\n"
            f"📆 Дедлайн: {deadline}{progress}\n"
            f"👁 Переглядів: <b>{view_stat['views']}</b>\n\n"
            f"{safe_description}"
        )
        is_available = quest.active and quest.status in {"open", "postponed"} and (quest.ends_at is None or quest.ends_at >= datetime.now())
        kb = quest_detail_keyboard(quest.id, part.status if part else None, quest.quest_type) if is_available else None
        photo = await telegram_photo_input(db, quest.image_path)
        if photo and len(text) <= 950:
            await call.message.answer_photo(photo, caption=text, reply_markup=kb)
        elif photo:
            await call.message.answer_photo(photo, caption=f"🎯 <b>{safe_title}</b>\n👁 {view_stat['views']} переглядів")
            await call.message.answer(text, reply_markup=kb)
        else:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()


@router.callback_query(F.data.startswith("quest_join:"))
async def quest_join(call: CallbackQuery, db: Database) -> None:
    quest_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await call.answer("Профіль не активований", show_alert=True)
            return
        quest = await session.get(Quest, quest_id)
        if not quest or not quest.active or quest.status not in {"open", "postponed"} or (quest.ends_at and quest.ends_at < datetime.now()):
            await call.answer("Квест недоступний", show_alert=True)
            return
        part = await session.scalar(select(QuestParticipation).where(QuestParticipation.quest_id == quest_id, QuestParticipation.user_id == user.id))
        if not part:
            session.add(QuestParticipation(quest_id=quest_id, user_id=user.id))
            await session.commit()
        elif part.status == "cancelled":
            part.status = "joined"
            part.joined_at = datetime.utcnow()
            part.completed_at = None
            part.approved_at = None
            await session.commit()
        await call.message.answer("🚀 Ти долучився/лась до квесту. Для командного квесту прогрес фіксує координатор; для індивідуального після виконання натисни «Позначити виконаним».")
        await call.answer()


@router.callback_query(F.data.startswith("quest_done:"))
async def quest_done(call: CallbackQuery, db: Database) -> None:
    quest_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            return
        quest = await session.get(Quest, quest_id)
        part = await session.scalar(select(QuestParticipation).where(QuestParticipation.quest_id == quest_id, QuestParticipation.user_id == user.id))
        if not quest or not quest.active or quest.status not in {"open", "postponed"} or (quest.ends_at and quest.ends_at < datetime.now()):
            await call.answer("Дедлайн квесту завершено", show_alert=True)
            return
        if not part or part.status not in {"joined", "returned"}:
            await call.answer("Спочатку візьми квест", show_alert=True)
            return
        part.status = "completed"
        part.completed_at = datetime.utcnow()
        await session.commit()
        await call.message.answer("✅ Виконання надіслано на підтвердження координатору.")
        await call.answer()


@router.callback_query(F.data.startswith("quest_cancel_join:"))
async def quest_cancel_join(call: CallbackQuery, db: Database) -> None:
    quest_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer()
            return
        part = await session.scalar(select(QuestParticipation).where(QuestParticipation.quest_id == quest_id, QuestParticipation.user_id == user.id))
        if not part or part.status == "approved":
            await call.answer("Участь уже не можна скасувати", show_alert=True)
            return
        if part.status != "cancelled":
            part.status = "cancelled"
            part.completed_at = None
            await session.commit()
        await call.message.answer("❌ Участь у квесті скасовано. Історію запису збережено.")
        await call.answer()
