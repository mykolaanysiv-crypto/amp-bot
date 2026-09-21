from __future__ import annotations

from html import escape

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from .participant_common import Database, UserStatus, get_user_by_tg, router
from ..model_domains import QuickXPChallenge, QuickXPCompletion, QuickXPQuestion
from ..quick_xp import (
    answer_quiz_question,
    available_quick_challenges,
    challenge_reward,
    complete_quick_challenge,
    kind_label,
    next_unanswered_quiz_question,
    parse_options,
    quick_xp_weekly_cap,
    weekly_quick_xp,
)
from ..states import QuickXPState


async def quick_xp_hub(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        rows = await available_quick_challenges(session, user.id, limit=20)
        used = await weekly_quick_xp(session, user.id)
        cap = await quick_xp_weekly_cap(session)
        remaining = max(0, cap - used)
        rewards = {item.id: await challenge_reward(session, item) for item in rows}

    b = InlineKeyboardBuilder()
    for item in rows:
        reward = rewards.get(item.id, int(item.xp_reward or 0))
        label = f"{kind_label(item.kind).split(' ', 1)[0]} {item.title} · до +{reward} XP" if item.kind == "quiz" else f"{kind_label(item.kind).split(' ', 1)[0]} {item.title} · +{reward} XP"
        b.button(text=label, callback_data=f"quickxp:{item.id}")
    if rows:
        b.button(text="✅ Уже виконано", callback_data="quickxp:done")
        b.button(text="📅 Заробити більше на подіях", callback_data="ux:join:events")
    b.adjust(1)
    if not rows:
        body = (
            "⚡ <b>Заробити XP</b>\n\n"
            "Зараз немає нових швидких завдань. Перевір пізніше або обери подію, квест чи волонтерську активність у «🚀 Долучитися»."
        )
    else:
        total_reward = sum(max(0, int(rewards.get(item.id, 0))) for item in rows)
        body = (
            "⚡ <b>Швидкі XP</b>\n\n"
            "Короткі завдання, які можна виконати прямо зараз. Кожне завдання зараховується лише один раз.\n\n"
            f"🎯 Доступно зараз: <b>{len(rows)}</b>\n"
            f"🎁 Тижневий ліміт: <b>{used}/{cap} XP</b>\n"
            f"⚡ Ще можна отримати цього тижня: <b>{remaining} XP</b>\n"
            f"💡 У доступних завданнях: <b>до {min(total_reward, remaining)} XP</b>\n\n"
            "Обери завдання нижче 👇"
        )
    await message.answer(body, reply_markup=b.as_markup() if rows else None)


@router.message(F.text == "⚡ Заробити XP")
async def quick_xp_menu(message: Message, db: Database) -> None:
    await quick_xp_hub(message, db)


@router.callback_query(F.data == "quickxp:hub")
async def quick_xp_hub_callback(call: CallbackQuery, db: Database) -> None:
    msg = call.message.model_copy(update={"from_user": call.from_user, "text": "⚡ Заробити XP"})
    await call.answer()
    await quick_xp_hub(msg, db)


@router.callback_query(F.data == "quickxp:done")
async def quick_xp_done(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer()
            return
        rows = list((await session.execute(
            select(QuickXPCompletion, QuickXPChallenge)
            .join(QuickXPChallenge, QuickXPChallenge.id == QuickXPCompletion.challenge_id)
            .where(QuickXPCompletion.user_id == user.id)
            .order_by(QuickXPCompletion.completed_at.desc()).limit(12)
        )).all())
    if not rows:
        text = "✅ <b>Виконані швидкі XP</b>\n\nПоки що тут порожньо."
    else:
        lines = ["✅ <b>Виконані швидкі XP</b>"]
        for completion, challenge in rows:
            lines.append(f"\n⚡ <b>{escape(challenge.title)}</b> · +{completion.xp_awarded} XP")
        text = "".join(lines)
    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До швидких XP", callback_data="quickxp:hub")]]))
    await call.answer()


async def _send_quiz_question(call: CallbackQuery, item: QuickXPChallenge, question: QuickXPQuestion, index: int, total: int) -> None:
    options = parse_options(question.options_json)
    b = InlineKeyboardBuilder()
    for idx, option in enumerate(options):
        b.button(text=option, callback_data=f"quickxp_quiz:{item.id}:{question.id}:{idx}")
    b.button(text="⬅️ До швидких XP", callback_data="quickxp:hub")
    b.adjust(1)
    await call.message.answer(
        f"🧠 <b>{escape(item.title)}</b>\n"
        f"Питання <b>{index}/{total}</b> · за правильну відповідь <b>+{question.xp_reward} XP</b>\n\n"
        f"<b>{escape(question.text)}</b>",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^quickxp:\d+$"))
async def quick_xp_detail(call: CallbackQuery, db: Database) -> None:
    challenge_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(QuickXPChallenge, challenge_id)
        if not user or not item:
            await call.answer("Завдання не знайдено", show_alert=True)
            return
        existing = await session.scalar(select(QuickXPCompletion).where(
            QuickXPCompletion.user_id == user.id,
            QuickXPCompletion.challenge_id == item.id,
        ))
        used = await weekly_quick_xp(session, user.id)
        cap = await quick_xp_weekly_cap(session)
        reward = await challenge_reward(session, item)
        if item.kind == "quiz" and not existing:
            question, index, total = await next_unanswered_quiz_question(session, user.id, item.id)
        else:
            question, index, total = None, 0, 0
    if existing:
        await call.answer("Це завдання вже виконано", show_alert=True)
        return
    if item.kind != "quiz" and used >= cap:
        await call.answer(f"Тижневий ліміт {cap} XP уже використано", show_alert=True)
        return

    if item.kind == "quiz":
        if not question:
            await call.answer("У цьому мініквізі поки немає доступних питань", show_alert=True)
            return
        await call.message.answer(
            f"🧠 <b>{escape(item.title)}</b>\n\n{escape(item.description or '')}\n\n"
            f"⏱ Приблизно {max(1, int(item.duration_minutes or 1))} хв\n"
            f"❓ Питань: <b>{total}</b>\n🎁 Максимум: <b>+{reward} XP</b>\n\n"
            "XP нараховується окремо за кожну правильну відповідь. Перша відповідь на питання є остаточною."
        )
        await _send_quiz_question(call, item, question, index, total)
        await call.answer()
        return

    b = InlineKeyboardBuilder()
    options = parse_options(item.options_json)
    if item.kind in {"video", "poll"} and options:
        for idx, option in enumerate(options):
            b.button(text=option, callback_data=f"quickxp_answer:{item.id}:{idx}")
    elif item.kind == "comment":
        b.button(text="💬 Відповісти", callback_data=f"quickxp_comment:{item.id}")
    if item.media_url:
        b.row(InlineKeyboardButton(text="🎥 Відкрити матеріал", url=item.media_url))
    b.button(text="⬅️ До швидких XP", callback_data="quickxp:hub")
    b.adjust(1)

    text = (
        f"{kind_label(item.kind)}\n"
        f"<b>{escape(item.title)}</b>\n\n"
        f"{escape(item.description or '')}\n\n"
        f"⏱ Приблизно {max(1, int(item.duration_minutes or 1))} хв\n"
        f"🎁 Нагорода: <b>+{reward} XP</b>"
    )
    if item.question:
        text += f"\n\n<b>{escape(item.question)}</b>"
    await call.message.answer(text, reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.regexp(r"^quickxp_quiz:\d+:\d+:\d+$"))
async def quick_xp_quiz_answer(call: CallbackQuery, db: Database) -> None:
    _, challenge_raw, question_raw, option_raw = call.data.split(":", 3)
    challenge_id, question_id, option = int(challenge_raw), int(question_raw), int(option_raw)
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(QuickXPChallenge, challenge_id)
        question = await session.get(QuickXPQuestion, question_id)
        if not user or not item or not question:
            await call.answer("Питання недоступне", show_alert=True)
            return
        accepted, correct, amount, total_xp, completed, message = await answer_quiz_question(
            session, user, item, question, option
        )
        completion = await session.scalar(select(QuickXPCompletion).where(
            QuickXPCompletion.challenge_id == challenge_id,
            QuickXPCompletion.user_id == user.id,
        )) if completed else None
        await session.commit()
    if not accepted:
        await call.answer(message, show_alert=True)
        return
    await call.answer(message, show_alert=True)
    if completed:
        earned = int(completion.xp_awarded or 0) if completion else amount
        await call.message.answer(
            f"✅ <b>Мініквіз завершено!</b>\n\n"
            f"{escape(item.title)}\n"
            f"🎁 За цей квіз отримано: <b>+{earned} XP</b>\n"
            f"⚡ Твій загальний досвід: <b>{total_xp} XP</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚡ Ще способи заробити XP", callback_data="quickxp:hub")]]),
        )
    else:
        icon = "✅" if correct else "➖"
        await call.message.answer(
            f"{icon} {escape(message)}\n\nПереходимо до наступного питання.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Наступне питання", callback_data=f"quickxp:{challenge_id}")]]),
        )


@router.callback_query(F.data.regexp(r"^quickxp_answer:\d+:\d+$"))
async def quick_xp_answer(call: CallbackQuery, db: Database) -> None:
    _, challenge_raw, option_raw = call.data.split(":", 2)
    challenge_id, option = int(challenge_raw), int(option_raw)
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(QuickXPChallenge, challenge_id)
        if not user or not item or item.kind == "quiz":
            await call.answer("Завдання недоступне", show_alert=True)
            return
        options = parse_options(item.options_json)
        if option < 0 or option >= len(options):
            await call.answer("Варіант недоступний", show_alert=True)
            return
        if item.kind == "video" and item.correct_option is not None and option != int(item.correct_option):
            await call.answer("Поки що ні 🙂 Спробуй ще раз", show_alert=True)
            return
        awarded, message, amount, total = await complete_quick_challenge(
            session, user, item, answer_text=options[option], answer_option=option,
        )
        await session.commit()
    if not awarded:
        await call.answer(message, show_alert=True)
        return
    await call.answer(f"+{amount} XP", show_alert=True)
    await call.message.answer(
        f"✅ <b>Готово! +{amount} XP</b>\n\n"
        f"{escape(item.title)} виконано.\n"
        f"⚡ Твій загальний досвід: <b>{total} XP</b>\n\n"
        "Хочеш заробити ще?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚡ Ще способи заробити XP", callback_data="quickxp:hub")]]),
    )


@router.callback_query(F.data.regexp(r"^quickxp_comment:\d+$"))
async def quick_xp_comment_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    challenge_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        item = await session.get(QuickXPChallenge, challenge_id)
        existing = await session.scalar(select(QuickXPCompletion).where(
            QuickXPCompletion.user_id == user.id,
            QuickXPCompletion.challenge_id == challenge_id,
        )) if user else None
    if not user or not item or existing:
        await call.answer("Завдання недоступне або вже виконане", show_alert=True)
        return
    await state.set_state(QuickXPState.comment)
    await state.update_data(quick_xp_challenge_id=challenge_id)
    await call.message.answer(
        f"💬 <b>{escape(item.title)}</b>\n\n"
        f"{escape(item.question or 'Напиши коротку відповідь одним повідомленням.')}"
    )
    await call.answer()


@router.message(QuickXPState.comment)
async def quick_xp_comment_finish(message: Message, state: FSMContext, db: Database) -> None:
    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer("Напиши хоча б кілька слів 🙂")
        return
    data = await state.get_data()
    challenge_id = int(data.get("quick_xp_challenge_id") or 0)
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        item = await session.get(QuickXPChallenge, challenge_id)
        if not user or not item:
            await state.clear()
            await message.answer("Завдання більше недоступне.")
            return
        awarded, result_message, amount, total = await complete_quick_challenge(
            session, user, item, answer_text=text,
        )
        await session.commit()
    await state.clear()
    if not awarded:
        await message.answer(result_message)
        return
    await message.answer(
        f"✅ <b>Готово! +{amount} XP</b>\n\n"
        f"Дякуємо за відповідь.\n⚡ Твій загальний досвід: <b>{total} XP</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚡ Ще способи заробити XP", callback_data="quickxp:hub")]]),
    )
