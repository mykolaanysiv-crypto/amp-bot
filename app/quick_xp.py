from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .domain_services import add_xp, xp_total
from .model_domains import (
    QuickXPAnswer,
    QuickXPChallenge,
    QuickXPCompletion,
    QuickXPQuestion,
    User,
    XPTransaction,
)
from .runtime_config import get_runtime_int
from .time_utils import clock

# Compatibility/default constant. Runtime value is read from System Settings.
QUICK_XP_WEEKLY_CAP = 30
QUICK_XP_KINDS = {"quiz", "video", "poll", "comment"}


def kind_label(kind: str) -> str:
    return {
        "quiz": "🧠 Мініквіз",
        "video": "🎥 Відео + питання",
        "poll": "📊 Мініопитування",
        "comment": "💬 Коротка відповідь",
    }.get(kind, "⚡ Швидкі XP")


def parse_options(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(v).strip() for v in data if str(v).strip()][:12]


def dump_options(values: list[str]) -> str:
    return json.dumps([str(v).strip() for v in values if str(v).strip()][:12], ensure_ascii=False)


def challenge_is_open(challenge: QuickXPChallenge, now=None) -> bool:
    now = now or clock.storage_utc()
    if not challenge.active:
        return False
    if challenge.starts_at and challenge.starts_at > now:
        return False
    if challenge.ends_at and challenge.ends_at < now:
        return False
    return True


async def quick_xp_weekly_cap(session) -> int:
    return await get_runtime_int(session, "quick_xp.weekly_cap", QUICK_XP_WEEKLY_CAP)


async def weekly_quick_xp(session, user_id: int, now=None) -> int:
    now_utc = now or clock.now_utc()
    local = clock.local_wall(now_utc)
    monday = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
    end = monday + timedelta(days=7)
    start_utc, end_utc = clock.local_period_to_storage_utc(monday, end)
    value = await session.scalar(
        select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(
            XPTransaction.user_id == user_id,
            XPTransaction.category == "quick_xp",
            XPTransaction.created_at >= start_utc,
            XPTransaction.created_at < end_utc,
        )
    )
    return max(0, int(value or 0))


async def quick_xp_questions(session, challenge_id: int) -> list[QuickXPQuestion]:
    return list((await session.scalars(
        select(QuickXPQuestion)
        .where(QuickXPQuestion.challenge_id == challenge_id)
        .order_by(QuickXPQuestion.sort_order.asc(), QuickXPQuestion.id.asc())
    )).all())


async def challenge_reward(session, challenge: QuickXPChallenge) -> int:
    if challenge.kind == "quiz":
        value = await session.scalar(
            select(func.coalesce(func.sum(QuickXPQuestion.xp_reward), 0)).where(
                QuickXPQuestion.challenge_id == challenge.id
            )
        )
        if int(value or 0) > 0:
            return int(value or 0)
    return max(0, int(challenge.xp_reward or 0))


async def sync_quiz_reward(session, challenge_id: int) -> int:
    challenge = await session.get(QuickXPChallenge, challenge_id)
    if not challenge:
        return 0
    if challenge.kind != "quiz":
        return max(0, int(challenge.xp_reward or 0))
    total = int(await session.scalar(
        select(func.coalesce(func.sum(QuickXPQuestion.xp_reward), 0)).where(
            QuickXPQuestion.challenge_id == challenge_id
        )
    ) or 0)
    challenge.xp_reward = total
    challenge.updated_at = clock.storage_utc()
    return total


async def available_quick_challenges(session, user_id: int, *, limit: int = 20) -> list[QuickXPChallenge]:
    now = clock.storage_utc()
    completed_ids = select(QuickXPCompletion.challenge_id).where(QuickXPCompletion.user_id == user_id)
    stmt = (
        select(QuickXPChallenge)
        .where(
            QuickXPChallenge.active == True,  # noqa: E712
            QuickXPChallenge.id.not_in(completed_ids),
            (QuickXPChallenge.starts_at.is_(None) | (QuickXPChallenge.starts_at <= now)),
            (QuickXPChallenge.ends_at.is_(None) | (QuickXPChallenge.ends_at >= now)),
        )
        .order_by(QuickXPChallenge.featured_home.desc(), QuickXPChallenge.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def complete_quick_challenge(
    session,
    user: User,
    challenge: QuickXPChallenge,
    *,
    answer_text: str = "",
    answer_option: int | None = None,
) -> tuple[bool, str, int, int]:
    """Complete a non-quiz Quick XP challenge once, respecting runtime weekly cap."""
    if not challenge_is_open(challenge):
        return False, "Це завдання зараз недоступне.", 0, await xp_total(session, user.id)
    existing = await session.scalar(
        select(QuickXPCompletion).where(
            QuickXPCompletion.challenge_id == challenge.id,
            QuickXPCompletion.user_id == user.id,
        )
    )
    if existing:
        return False, "Це завдання вже виконано.", 0, await xp_total(session, user.id)

    cap = await quick_xp_weekly_cap(session)
    used = await weekly_quick_xp(session, user.id)
    remaining = max(0, cap - used)
    if remaining <= 0:
        return False, f"Тижневий ліміт швидких XP ({cap}) уже використано.", 0, await xp_total(session, user.id)

    amount = min(max(1, int(challenge.xp_reward or 1)), remaining)
    completion = QuickXPCompletion(
        challenge_id=challenge.id,
        user_id=user.id,
        answer_text=(answer_text or "").strip()[:4000],
        answer_option=answer_option,
        xp_awarded=amount,
        completed_at=clock.storage_utc(),
    )
    try:
        async with session.begin_nested():
            session.add(completion)
            await session.flush()
    except IntegrityError:
        return False, "Це завдання вже виконано.", 0, await xp_total(session, user.id)

    total, _, _ = await add_xp(
        session,
        user,
        amount,
        f"Швидкі XP: {challenge.title}",
        category="quick_xp",
    )
    return True, "Готово", amount, total


async def next_unanswered_quiz_question(session, user_id: int, challenge_id: int) -> tuple[QuickXPQuestion | None, int, int]:
    questions = await quick_xp_questions(session, challenge_id)
    if not questions:
        return None, 0, 0
    answered = set((await session.scalars(
        select(QuickXPAnswer.question_id).where(
            QuickXPAnswer.user_id == user_id,
            QuickXPAnswer.challenge_id == challenge_id,
        )
    )).all())
    for index, question in enumerate(questions, start=1):
        if question.id not in answered:
            return question, index, len(questions)
    return None, len(questions), len(questions)


async def answer_quiz_question(
    session,
    user: User,
    challenge: QuickXPChallenge,
    question: QuickXPQuestion,
    answer_option: int,
) -> tuple[bool, bool, int, int, bool, str]:
    """Store one immutable first answer and award XP immediately when correct.

    Returns: (accepted, correct, xp_awarded, total_xp, quiz_completed, message)
    """
    if challenge.kind != "quiz" or question.challenge_id != challenge.id or not challenge_is_open(challenge):
        return False, False, 0, await xp_total(session, user.id), False, "Питання зараз недоступне."
    options = parse_options(question.options_json)
    if answer_option < 0 or answer_option >= len(options):
        return False, False, 0, await xp_total(session, user.id), False, "Варіант відповіді недоступний."

    existing = await session.scalar(select(QuickXPAnswer).where(
        QuickXPAnswer.question_id == question.id,
        QuickXPAnswer.user_id == user.id,
    ))
    if existing:
        next_q, _, total_count = await next_unanswered_quiz_question(session, user.id, challenge.id)
        done = next_q is None and total_count > 0
        return False, bool(existing.correct), int(existing.xp_awarded or 0), await xp_total(session, user.id), done, "На це питання ти вже відповів/ла."

    correct = answer_option == int(question.correct_option)
    amount = 0
    total = await xp_total(session, user.id)
    if correct:
        cap = await quick_xp_weekly_cap(session)
        used = await weekly_quick_xp(session, user.id)
        remaining = max(0, cap - used)
        amount = min(max(1, int(question.xp_reward or 1)), remaining)

    answer = QuickXPAnswer(
        challenge_id=challenge.id,
        question_id=question.id,
        user_id=user.id,
        answer_option=answer_option,
        correct=correct,
        xp_awarded=amount,
        answered_at=clock.storage_utc(),
    )
    try:
        async with session.begin_nested():
            session.add(answer)
            await session.flush()
    except IntegrityError:
        return False, False, 0, await xp_total(session, user.id), False, "На це питання вже є відповідь."

    if amount > 0:
        total, _, _ = await add_xp(
            session,
            user,
            amount,
            f"Швидкі XP: {challenge.title} — правильна відповідь",
            category="quick_xp",
        )

    questions_count = int(await session.scalar(
        select(func.count(QuickXPQuestion.id)).where(QuickXPQuestion.challenge_id == challenge.id)
    ) or 0)
    answers_count = int(await session.scalar(
        select(func.count(QuickXPAnswer.id)).where(
            QuickXPAnswer.challenge_id == challenge.id,
            QuickXPAnswer.user_id == user.id,
        )
    ) or 0)
    completed = questions_count > 0 and answers_count >= questions_count
    if completed:
        existing_completion = await session.scalar(select(QuickXPCompletion).where(
            QuickXPCompletion.challenge_id == challenge.id,
            QuickXPCompletion.user_id == user.id,
        ))
        if not existing_completion:
            earned = int(await session.scalar(
                select(func.coalesce(func.sum(QuickXPAnswer.xp_awarded), 0)).where(
                    QuickXPAnswer.challenge_id == challenge.id,
                    QuickXPAnswer.user_id == user.id,
                )
            ) or 0)
            session.add(QuickXPCompletion(
                challenge_id=challenge.id,
                user_id=user.id,
                answer_text="multi_quiz",
                answer_option=None,
                xp_awarded=earned,
                completed_at=clock.storage_utc(),
            ))
            await session.flush()

    if correct and amount > 0:
        message = f"Правильно! +{amount} XP"
    elif correct:
        message = "Правильно! Тижневий ліміт XP уже вичерпано."
    else:
        message = "Не цього разу — рухаємось далі 🙂"
    return True, correct, amount, total, completed, message
