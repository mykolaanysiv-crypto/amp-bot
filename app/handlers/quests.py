from __future__ import annotations

from ..observability import log_extra
from ..time_utils import clock

from datetime import datetime
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from ..db import Database
from ..keyboards import quest_detail_keyboard, quests_keyboard
from ..media import delete_stored_image, save_telegram_photo, telegram_photo_input
from ..model_domains import Quest, QuestParticipation, UserStatus
from ..domain_services import get_user_by_tg, log_audit
from ..engagement import process_expired_content
from ..content_views import content_view_stat, record_content_view
from ..states import QuestProofState

router = Router(name="quests")


async def _send_quests(target, db: Database) -> None:
    async with db.session_factory() as session:
        changed=await process_expired_content(session)
        if changed: await session.commit()
        quests=(await session.scalars(select(Quest).where(Quest.active == True, Quest.status.in_(["open","postponed"])).where((Quest.ends_at.is_(None)) | (Quest.ends_at >= clock.local_wall())).order_by(Quest.ends_at.asc()).limit(20))).all()  # noqa: E712
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
        except Exception as exc:
            await session.rollback()
            logging.getLogger("amp.quests").exception(
                "Lifecycle refresh failed while opening quest %s", quest_id,
                extra=log_extra("QUEST_LIFECYCLE_REFRESH_FAILED", entity_type="quest", entity_id=quest_id, exception_type=type(exc).__name__),
            )
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
        is_available = quest.active and quest.status in {"open", "postponed"} and (quest.ends_at is None or clock.local_wall_to_utc(quest.ends_at) >= clock.now_utc())
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
        if not quest or not quest.active or quest.status not in {"open", "postponed"} or (quest.ends_at and clock.local_wall_to_utc(quest.ends_at) < clock.now_utc()):
            await call.answer("Квест недоступний", show_alert=True)
            return
        part = await session.scalar(select(QuestParticipation).where(QuestParticipation.quest_id == quest_id, QuestParticipation.user_id == user.id))
        if not part:
            session.add(QuestParticipation(quest_id=quest_id, user_id=user.id))
            await session.commit()
        elif part.status == "cancelled":
            part.status = "joined"
            part.joined_at = clock.storage_utc()
            part.completed_at = None
            part.approved_at = None
            await session.commit()
        await call.message.answer("🚀 Ти долучився/лась до квесту. Для командного квесту прогрес фіксує координатор; для індивідуального після виконання натисни «Позначити виконаним».")
        await call.answer()


async def _quest_submission_context(session, tg_id: int, quest_id: int):
    user = await get_user_by_tg(session, tg_id)
    quest = await session.get(Quest, quest_id)
    part = None
    if user:
        part = await session.scalar(select(QuestParticipation).where(
            QuestParticipation.quest_id == quest_id, QuestParticipation.user_id == user.id
        ))
    return user, quest, part


def _quest_photo_choice_keyboard(quest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📷 Так, додати фото", callback_data=f"quest_proof_yes:{quest_id}"),
        InlineKeyboardButton(text="➡️ Ні, без фото", callback_data=f"quest_proof_no:{quest_id}"),
    ]])


async def _mark_quest_submitted(session, quest: Quest, part: QuestParticipation, user, *, proof: str | None) -> None:
    part.status = "completed"
    part.completed_at = clock.storage_utc()
    if proof is not None:
        part.proof_photo_path = proof
    await log_audit(
        session, "quest_submission", actor_label=f"tg:{user.tg_id}", entity_type="quest_participation", entity_id=part.id,
        details=f"quest={quest.id}; proof={'yes' if part.proof_photo_path else 'no'}",
    )


@router.callback_query(F.data.startswith("quest_done:"))
async def quest_done(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    quest_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user, quest, part = await _quest_submission_context(session, call.from_user.id, quest_id)
        if not user:
            await call.answer("Профіль не знайдено", show_alert=True)
            return
        if not quest or not quest.active or quest.status not in {"open", "postponed"} or (quest.ends_at and clock.local_wall_to_utc(quest.ends_at) < clock.now_utc()):
            await call.answer("Дедлайн квесту завершено", show_alert=True)
            return
        if not part or part.status not in {"joined", "returned"}:
            await call.answer("Спочатку візьми квест", show_alert=True)
            return
        await state.clear()
        await state.update_data(quest_proof_quest_id=quest_id)
        await call.message.answer(
            "✅ <b>Квест виконано?</b>\n\nЄ фото, яке підтверджує виконання?",
            reply_markup=_quest_photo_choice_keyboard(quest_id),
        )
        await call.answer()


@router.callback_query(F.data.startswith("quest_proof_no:"))
async def quest_proof_no(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    quest_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user, quest, part = await _quest_submission_context(session, call.from_user.id, quest_id)
        if not user or not quest or not part or part.status not in {"joined", "returned"}:
            await call.answer("Запит уже неактуальний", show_alert=True)
            return
        old_proof = part.proof_photo_path
        part.proof_photo_path = None
        await _mark_quest_submitted(session, quest, part, user, proof=None)
        await session.commit()
    if old_proof:
        await delete_stored_image(db, old_proof)
    await state.clear()
    await call.message.answer("🙏 Дякуємо! Ваш запит на виконання квесту передано на обробку координатору.")
    await call.answer("Надіслано")


@router.callback_query(F.data.startswith("quest_proof_yes:"))
async def quest_proof_yes(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    quest_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user, quest, part = await _quest_submission_context(session, call.from_user.id, quest_id)
        if not user or not quest or not part or part.status not in {"joined", "returned"}:
            await call.answer("Запит уже неактуальний", show_alert=True)
            return
    await state.set_state(QuestProofState.photo)
    await state.update_data(quest_proof_quest_id=quest_id)
    await call.message.answer("📷 Надішліть одне фото-підтвердження виконання квесту.")
    await call.answer()


@router.message(QuestProofState.photo, F.photo)
async def quest_proof_photo(message: Message, db: Database, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    quest_id = int(data.get("quest_proof_quest_id") or 0)
    async with db.session_factory() as session:
        user, quest, part = await _quest_submission_context(session, message.from_user.id, quest_id)
        if not user or not quest or not part or part.status not in {"joined", "returned"}:
            await state.clear()
            await message.answer("ℹ️ Цей запит уже неактуальний.")
            return
        try:
            proof = await save_telegram_photo(bot, message.photo[-1].file_id, "quest_proofs", db, max_mb=20)
        except ValueError as exc:
            await message.answer(f"⚠️ {escape(str(exc))}")
            return
        old = part.proof_photo_path
        await _mark_quest_submitted(session, quest, part, user, proof=proof)
        await session.commit()
    if old and old != proof:
        await delete_stored_image(db, old)
    await state.clear()
    await message.answer("🙏 Дякуємо! Фото додано, а ваш запит на виконання квесту передано на обробку координатору.")


@router.message(QuestProofState.photo)
async def quest_proof_wrong_type(message: Message) -> None:
    await message.answer("📷 Будь ласка, надішліть саме фото. Якщо фото немає — поверніться до квесту й оберіть «Ні, без фото».")


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
