from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .domain_services import add_xp, xp_total
from .model_domains import QuickXPChallenge, QuickXPCompletion, User, XPTransaction
from .time_utils import clock

QUICK_XP_WEEKLY_CAP = 15
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
    return [str(v).strip() for v in data if str(v).strip()][:8]


def dump_options(values: list[str]) -> str:
    return json.dumps([str(v).strip() for v in values if str(v).strip()][:8], ensure_ascii=False)


def challenge_is_open(challenge: QuickXPChallenge, now=None) -> bool:
    now = now or clock.storage_utc()
    if not challenge.active:
        return False
    if challenge.starts_at and challenge.starts_at > now:
        return False
    if challenge.ends_at and challenge.ends_at < now:
        return False
    return True


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
        .order_by(QuickXPChallenge.featured_home.desc(), QuickXPChallenge.sort_order.asc(), QuickXPChallenge.created_at.desc())
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
    """Complete once, respecting the weekly micro-XP cap.

    Returns (awarded, message, xp_awarded, total_xp).
    """
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

    used = await weekly_quick_xp(session, user.id)
    remaining = max(0, QUICK_XP_WEEKLY_CAP - used)
    if remaining <= 0:
        return False, f"Тижневий ліміт швидких XP ({QUICK_XP_WEEKLY_CAP}) уже використано.", 0, await xp_total(session, user.id)

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
