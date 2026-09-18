from __future__ import annotations

from ..time_utils import clock

import json
import logging
from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from ..db import Database
from ..models import Survey, SurveyQuestion, SurveyResponse, User, UserStatus
from ..media import telegram_photo_input
from ..services import get_user_by_tg
from ..workflows import complete_survey_once
from ..states import SurveyState
from ..content_views import content_view_stat, record_content_view
from ..observability import log_extra
from ..survey_audience import survey_available_to_user

router = Router(name="surveys")


def _options(question: SurveyQuestion) -> list[str]:
    return [x.strip() for x in (question.options_text or "").splitlines() if x.strip()]


def _survey_available(survey: Survey | None, now: datetime | None = None) -> bool:
    if not survey or survey.status != "published":
        return False
    if now is None:
        now_utc = clock.now_utc()
    elif now.tzinfo is None:
        now_utc = clock.from_storage_utc(now) or clock.now_utc()
    else:
        now_utc = clock.ensure_utc(now)
    storage_now = clock.storage_utc(now_utc)
    if survey.starts_at and survey.starts_at > storage_now:
        return False
    if survey.ends_at and clock.local_wall_to_utc(survey.ends_at) < now_utc:
        return False
    return True


async def _active(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value:
        return None
    return user


async def _available_surveys(session, user_id: int) -> list[tuple[Survey, bool]]:
    now_utc = clock.now_utc()
    storage_now = clock.storage_utc(now_utc)
    local_now = clock.local_wall(now_utc)
    surveys = list((await session.scalars(
        select(Survey)
        .where(Survey.status == "published")
        .where((Survey.starts_at.is_(None)) | (Survey.starts_at <= storage_now))
        .where((Survey.ends_at.is_(None)) | (Survey.ends_at >= local_now))
        .order_by(Survey.created_at.desc())
    )).all())
    done_ids = set((await session.scalars(
        select(SurveyResponse.survey_id).where(SurveyResponse.user_id == user_id)
    )).all())
    visible = []
    for survey in surveys:
        if await survey_available_to_user(session, survey, user_id):
            visible.append((survey, survey.id in done_ids))
    return visible


@router.message(F.text == "📋 Опитування")
async def surveys_menu(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    async with db.session_factory() as session:
        user = await _active(session, message.from_user.id)
        if not user:
            await message.answer("Профіль ще не активований.")
            return
        rows = await _available_surveys(session, user.id)
    b = InlineKeyboardBuilder()
    for survey, done in rows:
        prefix = "✅" if done else "📋"
        b.button(text=f"{prefix} {survey.title}", callback_data=f"survey:view:{survey.id}")
    b.adjust(1)
    text = "📋 <b>Опитування АМП</b>\n\nТут з’являються актуальні опитування. За деякі з них можна отримати XP після повного проходження."
    if not rows:
        text += "\n\nНаразі активних опитувань немає."
    await message.answer(text, reply_markup=b.as_markup() if rows else None)


@router.callback_query(F.data.startswith("survey:view:"))
async def survey_view(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    survey_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        survey = await session.get(Survey, survey_id)
        existing = None if not user else await session.scalar(select(SurveyResponse).where(SurveyResponse.survey_id == survey_id, SurveyResponse.user_id == user.id))
        questions_count = int(await session.scalar(select(func.count(SurveyQuestion.id)).where(SurveyQuestion.survey_id == survey_id)) or 0)
        eligible = bool(user and await survey_available_to_user(session, survey, user.id))
        if eligible and _survey_available(survey):
            await record_content_view(session, "survey", survey_id, user=user)
            await session.flush()
            view_stat = await content_view_stat(session, "survey", survey_id)
            await session.commit()
        else:
            view_stat = {"views": 0, "unique": 0}
    if not user or not eligible or not _survey_available(survey):
        await call.answer("Опитування недоступне для вашого профілю або його термін завершився", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    if existing:
        b.button(text="✅ Уже пройдено", callback_data="noop")
    elif questions_count:
        b.button(text="▶️ Почати опитування", callback_data=f"survey:start:{survey.id}")
    b.button(text="⬅️ До опитувань", callback_data="survey:list")
    b.adjust(1)
    deadline = survey.ends_at.strftime("%d.%m.%Y %H:%M") if survey.ends_at else "без дедлайну"
    safe_title = escape(survey.title or "Опитування")
    safe_description = escape(survey.description or "Без додаткового опису.")
    await call.message.answer(
        f"📋 <b>{safe_title}</b>\n\n{safe_description}\n\n"
        f"❓ Питань: <b>{questions_count}</b>\n🎁 Нагорода: <b>{survey.xp_reward} XP</b>\n"
        f"👁 Переглядів: <b>{view_stat['views']}</b>\n⏳ Дедлайн: <b>{deadline}</b>",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "survey:list")
async def survey_list_callback(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        if not user:
            await call.answer("Профіль не активований", show_alert=True)
            return
        rows = await _available_surveys(session, user.id)
    b = InlineKeyboardBuilder()
    for survey, done in rows:
        b.button(text=f"{'✅' if done else '📋'} {survey.title}", callback_data=f"survey:view:{survey.id}")
    b.adjust(1)
    await call.message.answer("📋 <b>Актуальні опитування</b>", reply_markup=b.as_markup() if rows else None)
    await call.answer()


async def _load_progress(session, state: FSMContext, tg_id: int):
    data = await state.get_data()
    survey_id = int(data.get("survey_id") or 0)
    idx = int(data.get("question_index") or 0)
    user = await _active(session, tg_id)
    survey = await session.get(Survey, survey_id) if survey_id else None
    questions = list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id).order_by(SurveyQuestion.sort_order, SurveyQuestion.id))).all()) if survey else []
    eligible = bool(user and survey and await survey_available_to_user(session, survey, user.id))
    return data, survey, questions, idx, user, eligible


async def _finish_survey(target, db: Database, state: FSMContext, user: User, survey: Survey, answers: dict) -> None:
    reward = 0
    async with db.session_factory() as session:
        fresh_user = await session.get(User, user.id)
        fresh_survey = await session.get(Survey, survey.id)
        if not fresh_user or not fresh_survey:
            await state.clear()
            await target.answer("Опитування більше недоступне.")
            return
        response, reward, status = await complete_survey_once(session, fresh_survey, fresh_user, answers)
        if status == "already_completed":
            await state.clear()
            await target.answer("✅ Це опитування вже було завершено.")
            return
        if status == "closed":
            await state.clear()
            await target.answer("⏳ Термін опитування вже завершився. Відповіді не збережено.")
            return
        await session.commit()
    await state.clear()
    suffix = f"\n🎁 Нараховано <b>+{reward} XP</b>." if reward else ""
    await target.answer(f"✅ <b>Дякуємо!</b> Опитування «{survey.title}» завершено.{suffix}")



async def _send_question(target, db: Database, state: FSMContext, tg_id: int) -> None:
    async with db.session_factory() as session:
        data, survey, questions, idx, user, eligible = await _load_progress(session, state, tg_id)
    if not user or not eligible or not _survey_available(survey):
        await state.clear()
        await target.answer("Опитування більше недоступне або його термін завершився.")
        return
    if idx >= len(questions):
        await _finish_survey(target, db, state, user, survey, data.get("answers", {}))
        return
    q = questions[idx]
    header = f"📋 <b>{survey.title}</b>\n\n<b>{idx + 1}/{len(questions)}.</b> {q.text}"
    if q.question_type == "text":
        await state.set_state(SurveyState.text_answer)
        await state.update_data(current_question_id=q.id)
        text = header + "\n\n✍️ Напиши відповідь повідомленням."
        photo = await telegram_photo_input(db, getattr(q, "image_path", None))
        if photo:
            await target.answer_photo(photo=photo, caption=text)
        else:
            await target.answer(text)
        return
    opts = _options(q)
    b = InlineKeyboardBuilder()
    if q.question_type == "multiple":
        selected = set((data.get("multi_selected") or {}).get(str(q.id), []))
        for i, option in enumerate(opts):
            mark = "☑️" if i in selected else "▫️"
            b.button(text=f"{mark} {option}", callback_data=f"survey:multi:{q.id}:{i}")
        b.button(text="✅ Готово", callback_data=f"survey:multi_done:{q.id}")
    else:
        for i, option in enumerate(opts):
            b.button(text=option, callback_data=f"survey:single:{q.id}:{i}")
    b.adjust(1)
    photo = await telegram_photo_input(db, getattr(q, "image_path", None))
    if photo:
        await target.answer_photo(photo=photo, caption=header, reply_markup=b.as_markup())
    else:
        await target.answer(header, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("survey:start:"))
async def survey_start(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    survey_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        survey = await session.get(Survey, survey_id)
        existing = None if not user else await session.scalar(select(SurveyResponse).where(SurveyResponse.survey_id == survey_id, SurveyResponse.user_id == user.id))
        eligible = bool(user and survey and await survey_available_to_user(session, survey, user.id))
    if not user or not eligible or not _survey_available(survey) or existing:
        await call.answer("Опитування недоступне, завершилося або вже пройдене", show_alert=True)
        return
    await state.clear()
    await state.update_data(survey_id=survey_id, question_index=0, answers={}, multi_selected={})
    await _send_question(call.message, db, state, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("survey:single:"))
async def survey_single(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    _, _, qid_raw, idx_raw = call.data.split(":")
    qid, option_idx = int(qid_raw), int(idx_raw)
    async with db.session_factory() as session:
        q = await session.get(SurveyQuestion, qid)
    if not q:
        await call.answer("Питання не знайдено", show_alert=True); return
    opts = _options(q)
    if option_idx >= len(opts):
        await call.answer("Варіант недоступний", show_alert=True); return
    data = await state.get_data(); answers = dict(data.get("answers") or {})
    answers[str(qid)] = opts[option_idx]
    await state.update_data(answers=answers, question_index=int(data.get("question_index") or 0) + 1)
    await _send_question(call.message, db, state, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("survey:multi:"))
async def survey_multi(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    _, _, qid_raw, idx_raw = call.data.split(":")
    qid, option_idx = int(qid_raw), int(idx_raw)
    data = await state.get_data(); all_selected = dict(data.get("multi_selected") or {})
    selected = set(all_selected.get(str(qid), []))
    if option_idx in selected: selected.remove(option_idx)
    else: selected.add(option_idx)
    all_selected[str(qid)] = sorted(selected)
    await state.update_data(multi_selected=all_selected)
    # Toggle checkmarks in the same Telegram message instead of sending a new
    # copy of the question for every tap. This keeps multi-select fast and tidy.
    async with db.session_factory() as session:
        q = await session.get(SurveyQuestion, qid)
    if not q:
        await call.answer("Питання не знайдено", show_alert=True)
        return
    opts = _options(q)
    b = InlineKeyboardBuilder()
    for i, option in enumerate(opts):
        mark = "☑️" if i in selected else "▫️"
        b.button(text=f"{mark} {option}", callback_data=f"survey:multi:{qid}:{i}")
    b.button(text="✅ Готово", callback_data=f"survey:multi_done:{qid}")
    b.adjust(1)
    try:
        await call.message.edit_reply_markup(reply_markup=b.as_markup())
    except Exception as exc:
        # Telegram may reject a no-op edit; the selection is still persisted.
        logging.getLogger("amp.surveys").debug(
            "Не вдалося оновити multi-select markup",
            extra=log_extra("TG_SURVEY_MULTI_MARKUP_EDIT_FAILED", tg_id=call.from_user.id, question_id=qid, exception_type=type(exc).__name__),
        )
    await call.answer("Обрано" if option_idx in selected else "Знято")


@router.callback_query(F.data.startswith("survey:multi_done:"))
async def survey_multi_done(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    qid = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        q = await session.get(SurveyQuestion, qid)
    if not q:
        await call.answer("Питання не знайдено", show_alert=True); return
    data = await state.get_data(); selected = list((data.get("multi_selected") or {}).get(str(qid), [])); opts = _options(q)
    if q.required and not selected:
        await call.answer("Оберіть хоча б один варіант", show_alert=True); return
    answers = dict(data.get("answers") or {})
    answers[str(qid)] = [opts[i] for i in selected if i < len(opts)]
    await state.update_data(answers=answers, question_index=int(data.get("question_index") or 0) + 1)
    await _send_question(call.message, db, state, call.from_user.id)
    await call.answer()


@router.message(SurveyState.text_answer)
async def survey_text_answer(message: Message, db: Database, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Напиши текстову відповідь.")
        return
    data = await state.get_data(); qid = str(data.get("current_question_id") or "")
    answers = dict(data.get("answers") or {}); answers[qid] = text
    await state.update_data(answers=answers, question_index=int(data.get("question_index") or 0) + 1, current_question_id=None)
    await state.set_state(None)
    await _send_question(message, db, state, message.from_user.id)
