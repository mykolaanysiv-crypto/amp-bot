from __future__ import annotations

from .time_utils import clock

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Badge,
    Event,
    EventRegistration,
    ParticipationStreak,
    StreakFreeze,
    Season,
    User,
    UserBadge,
    UserStatus,
    XPTransaction,
)
from .runtime_config import get_runtime_int


@dataclass(frozen=True)
class League:
    code: str
    title: str
    icon: str
    min_xp: int
    max_xp: int | None


LEAGUES: tuple[League, ...] = (
    League("bronze", "Бронзова ліга", "🥉", 0, 99),
    League("silver", "Срібна ліга", "🥈", 100, 249),
    League("gold", "Золота ліга", "🥇", 250, 499),
    League("platinum", "Платинова ліга", "💠", 500, 999),
    League("diamond", "Діамантова ліга", "💎", 1000, 1499),
    League("legendary", "Легендарна ліга", "👑", 1500, None),
)

SUPER_STREAK_BADGE_NAME = "Суперсерія 30 днів"
WEEKLY_STREAK_CATEGORIES = {"event", "quest", "team_quest", "activity", "task", "survey", "idea_approved", "referral"}
SUPER_STREAK_BADGE_ICON = "🔥"
MAX_FREEZE_DAYS_PER_QUARTER = 14

SUPER_STREAK_BADGE_DESCRIPTION = (
    "За серію відвідування подій, що тривала щонайменше 30 днів "
    "з дотриманням правил суперсерії."
)


def league_for_xp(xp: int) -> League:
    value = max(0, int(xp or 0))
    for league in LEAGUES:
        if value >= league.min_xp and (league.max_xp is None or value <= league.max_xp):
            return league
    return LEAGUES[-1]


def league_progress(xp: int) -> tuple[League, int, int | None]:
    league = league_for_xp(xp)
    if league.max_xp is None:
        return league, max(0, xp - league.min_xp), None
    width = league.max_xp - league.min_xp + 1
    return league, max(0, xp - league.min_xp), width


async def season_leaderboard_rows(session: AsyncSession, season: Season, limit: int | None = None):
    stmt = (
        select(User.id, User.full_name, func.coalesce(func.sum(XPTransaction.amount), 0).label("xp"))
        .outerjoin(
            XPTransaction,
            (XPTransaction.user_id == User.id) & (XPTransaction.season_id == season.id),
        )
        .where(
            User.status == UserStatus.ACTIVE.value,
            or_(User.leaderboard_opt_in == True, User.leaderboard_opt_in.is_(None)),  # noqa: E712
        )
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(XPTransaction.amount), 0).desc(), User.full_name.asc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return (await session.execute(stmt)).all()


async def league_leaderboard_rows(session: AsyncSession, season: Season, league: League):
    xp_sum = func.coalesce(func.sum(XPTransaction.amount), 0)
    stmt = (
        select(User.id, User.full_name, xp_sum.label("xp"))
        .outerjoin(
            XPTransaction,
            (XPTransaction.user_id == User.id) & (XPTransaction.season_id == season.id),
        )
        .where(
            User.status == UserStatus.ACTIVE.value,
            or_(User.leaderboard_opt_in == True, User.leaderboard_opt_in.is_(None)),  # noqa: E712
        )
        .group_by(User.id, User.full_name)
        .having(xp_sum >= league.min_xp)
        .order_by(xp_sum.desc(), User.full_name.asc())
    )
    if league.max_xp is not None:
        stmt = stmt.having(xp_sum <= league.max_xp)
    return (await session.execute(stmt)).all()


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def quarter_key(value: date | datetime) -> str:
    d = value.date() if isinstance(value, datetime) else value
    return f"{d.year}-Q{((d.month - 1) // 3) + 1}"


async def _freeze_ranges(session: AsyncSession, user_id: int) -> list[StreakFreeze]:
    return list((await session.scalars(
        select(StreakFreeze)
        .where(StreakFreeze.user_id == user_id)
        .order_by(StreakFreeze.starts_at.asc(), StreakFreeze.id.asc())
    )).all())


def _is_frozen(moment: datetime, freezes: list[StreakFreeze]) -> bool:
    return any(row.starts_at <= moment < row.ends_at for row in freezes)


def _protected_weeks(freezes: list[StreakFreeze], now: datetime) -> set[date]:
    protected: set[date] = set()
    current_week = _week_start(now.date())
    for row in freezes:
        start_week = _week_start(row.starts_at.date())
        end_week = _week_start((row.ends_at - timedelta(seconds=1)).date())
        cursor = start_week
        while cursor <= end_week and cursor <= current_week:
            protected.add(cursor)
            cursor += timedelta(days=7)
    return protected


async def freeze_days_used(session: AsyncSession, user_id: int, *, when: datetime | None = None) -> int:
    when = when or clock.storage_utc()
    qkey = quarter_key(when)
    return int(await session.scalar(
        select(func.coalesce(func.sum(StreakFreeze.days), 0)).where(
            StreakFreeze.user_id == user_id,
            StreakFreeze.quarter_key == qkey,
        )
    ) or 0)


async def create_streak_freeze(
    session: AsyncSession,
    user_id: int,
    days: int,
    *,
    created_by_label: str = "web",
    note: str = "",
    now: datetime | None = None,
) -> StreakFreeze:
    now = now or clock.storage_utc()
    days = int(days or 0)
    if days < 1:
        raise ValueError("Вкажіть щонайменше 1 день заморозки")
    latest_active = await session.scalar(
        select(StreakFreeze)
        .where(StreakFreeze.user_id == user_id, StreakFreeze.ends_at > now)
        .order_by(StreakFreeze.ends_at.desc())
    )
    starts_at = latest_active.ends_at if latest_active and latest_active.ends_at > now else now
    qkey = quarter_key(starts_at)
    used = int(await session.scalar(
        select(func.coalesce(func.sum(StreakFreeze.days), 0)).where(
            StreakFreeze.user_id == user_id,
            StreakFreeze.quarter_key == qkey,
        )
    ) or 0)
    freeze_limit = await get_runtime_int(session, "streak.freeze_limit_quarter")
    remaining = max(0, freeze_limit - used)
    if days > remaining:
        raise ValueError(f"У цьому кварталі доступно ще {remaining} дн. заморозки з {freeze_limit}")
    row = StreakFreeze(
        user_id=user_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=days),
        days=days,
        quarter_key=qkey,
        created_by_label=created_by_label,
        note=note.strip(),
    )
    session.add(row)
    await session.flush()
    return row


async def streak_freeze_summary(
    session: AsyncSession,
    user_ids: Iterable[int],
    *,
    now: datetime | None = None,
) -> dict[int, dict[str, object]]:
    now = now or clock.storage_utc()
    ids = list({int(x) for x in user_ids})
    if not ids:
        return {}
    rows = list((await session.scalars(
        select(StreakFreeze).where(StreakFreeze.user_id.in_(ids)).order_by(StreakFreeze.starts_at.asc())
    )).all())
    qkey = quarter_key(now)
    freeze_limit = await get_runtime_int(session, "streak.freeze_limit_quarter")
    result = {uid: {"active_until": None, "used": 0, "remaining": freeze_limit, "count": 0} for uid in ids}
    for row in rows:
        item = result.setdefault(row.user_id, {"active_until": None, "used": 0, "remaining": freeze_limit, "count": 0})
        item["count"] = int(item["count"]) + 1
        if row.quarter_key == qkey:
            item["used"] = int(item["used"]) + int(row.days or 0)
        if row.ends_at > now and (item["active_until"] is None or row.ends_at > item["active_until"]):
            item["active_until"] = row.ends_at
    for item in result.values():
        item["remaining"] = max(0, freeze_limit - int(item["used"]))
    return result


async def _weekly_streak(
    session: AsyncSession,
    user_id: int,
    now: datetime,
    freezes: list[StreakFreeze] | None = None,
) -> tuple[int, str | None]:
    dates = (await session.scalars(
        select(XPTransaction.created_at).where(
            XPTransaction.user_id == user_id,
            XPTransaction.amount > 0,
            XPTransaction.category.in_(WEEKLY_STREAK_CATEGORIES),
        )
    )).all()
    active_weeks = {_week_start(dt.date()) for dt in dates if dt}
    protected_weeks = _protected_weeks(freezes or [], now)
    if not active_weeks:
        return 0, None

    current = _week_start(now.date())
    # The current calendar week is still open. If there has not been activity
    # yet, keep the streak alive from the previous completed week. Frozen weeks
    # are skipped without increasing the streak, so a freeze preserves rather
    # than artificially grows the result.
    cursor = current if current in active_weeks else current - timedelta(days=7)
    streak = 0
    last_active: date | None = None
    safety = 0
    while safety < 520:
        safety += 1
        if cursor in active_weeks:
            streak += 1
            if last_active is None:
                last_active = cursor
            cursor -= timedelta(days=7)
            continue
        if cursor in protected_weeks:
            cursor -= timedelta(days=7)
            continue
        break
    return streak, _week_key(last_active) if streak and last_active else None


async def _ensure_super_streak_badge(session: AsyncSession, threshold_days: int) -> Badge:
    # Keep one canonical super-streak badge even when the threshold is changed
    # from Settings. Older installations used super_streak_30d / a fixed name.
    badge = await session.scalar(
        select(Badge).where(Badge.criteria_type.in_(["super_streak_days", "super_streak_30d"])).order_by(Badge.id.asc())
    )
    if not badge:
        badge = await session.scalar(select(Badge).where(Badge.name == SUPER_STREAK_BADGE_NAME))
    title = f"Суперсерія {threshold_days} днів"
    description = f"За серію відвідування подій, що тривала щонайменше {threshold_days} днів з дотриманням правил суперсерії."
    if badge:
        badge.name = title
        badge.icon = SUPER_STREAK_BADGE_ICON
        badge.description = description
        badge.criteria_type = "super_streak_days"
        badge.criteria_value = threshold_days
        badge.active = True
        badge.automatic = True
        return badge
    badge = Badge(
        name=title, icon=SUPER_STREAK_BADGE_ICON, description=description,
        criteria_type="super_streak_days", criteria_value=threshold_days,
        active=True, automatic=True, badge_type="general",
    )
    session.add(badge)
    await session.flush()
    return badge


async def _award_super_streak_badge_if_needed(
    session: AsyncSession,
    user: User,
    row: ParticipationStreak,
    now: datetime,
) -> bool:
    threshold_days = await get_runtime_int(session, "streak.badge_days")
    if not row.event_started_at or row.event_streak < 2:
        return False
    if (now - row.event_started_at).days < threshold_days:
        return False
    badge = await _ensure_super_streak_badge(session, threshold_days)
    existing = await session.scalar(
        select(UserBadge).where(UserBadge.user_id == user.id, UserBadge.badge_id == badge.id)
    )
    if existing:
        return False
    session.add(UserBadge(user_id=user.id, badge_id=badge.id, awarded_by=None))
    return True


async def get_or_create_streak(session: AsyncSession, user_id: int) -> ParticipationStreak:
    row = await session.scalar(select(ParticipationStreak).where(ParticipationStreak.user_id == user_id))
    if row:
        return row
    row = ParticipationStreak(user_id=user_id)
    session.add(row)
    await session.flush()
    return row


async def refresh_user_streak(
    session: AsyncSession,
    user: User,
    *,
    now: datetime | None = None,
    rebuild_events: bool = False,
) -> tuple[ParticipationStreak, bool]:
    """Refresh cached weekly and event streaks.

    Weekly streak = consecutive ISO calendar weeks with at least one positive XP
    transaction. Current week may still be empty without breaking the streak.

    Super event streak starts with an attended event. It survives one missed event
    in a row and at most two missed events in total. A second consecutive miss or
    third total miss breaks it. The previous run is stored as recoverable so a
    special reward can restore it once.
    """
    now = now or clock.storage_utc()
    row = await get_or_create_streak(session, user.id)
    if row.manual_lock and not rebuild_events:
        row.updated_at = now
        badge_awarded = await _award_super_streak_badge_if_needed(session, user, row, now)
        return row, badge_awarded

    if rebuild_events:
        row.manual_lock = False

    freezes = await _freeze_ranges(session, user.id)
    weekly, week_key = await _weekly_streak(session, user.id, now, freezes)
    row.weekly_streak = weekly
    row.weekly_best = max(int(row.weekly_best or 0), weekly)
    row.weekly_last_key = week_key

    if rebuild_events:
        row.event_streak = 0
        row.event_started_at = None
        row.event_consecutive_misses = 0
        row.event_total_misses = 0
        row.event_last_processed_at = None
        row.recoverable_event_streak = 0
        row.recoverable_event_started_at = None
        row.recoverable_saved_at = None

    stmt = select(Event).where(
        Event.starts_at <= now,
        Event.status.notin_(["cancelled", "draft"]),
    )
    if row.event_last_processed_at:
        stmt = stmt.where(Event.starts_at > row.event_last_processed_at)
    consecutive_miss_limit = await get_runtime_int(session, "streak.super_consecutive_misses")
    total_miss_limit = await get_runtime_int(session, "streak.super_total_misses")
    events = (await session.scalars(stmt.order_by(Event.starts_at.asc(), Event.id.asc()))).all()

    if events:
        event_ids = [e.id for e in events]
        regs = (await session.scalars(
            select(EventRegistration).where(
                EventRegistration.user_id == user.id,
                EventRegistration.event_id.in_(event_ids),
            )
        )).all()
        reg_map = {r.event_id: r for r in regs}

        for event in events:
            reg = reg_map.get(event.id)
            attended = bool(reg and reg.status == "attended")
            if attended:
                if int(row.event_streak or 0) <= 0:
                    row.event_started_at = event.starts_at
                    row.event_streak = 1
                    row.event_total_misses = 0
                    row.event_consecutive_misses = 0
                else:
                    row.event_streak = int(row.event_streak or 0) + 1
                    row.event_consecutive_misses = 0
                row.event_best = max(int(row.event_best or 0), int(row.event_streak or 0))
            elif int(row.event_streak or 0) > 0 and _is_frozen(event.starts_at, freezes):
                # A missed event inside an approved freeze window does not
                # consume either the consecutive or total miss allowance.
                pass
            elif int(row.event_streak or 0) > 0:
                row.event_consecutive_misses = int(row.event_consecutive_misses or 0) + 1
                row.event_total_misses = int(row.event_total_misses or 0) + 1
                if row.event_consecutive_misses > consecutive_miss_limit or row.event_total_misses > total_miss_limit:
                    # Preserve the run before the break. The processed event is
                    # not revisited, so buying a restore reward truly revives it.
                    row.recoverable_event_streak = int(row.event_streak or 0)
                    row.recoverable_event_started_at = row.event_started_at
                    row.recoverable_saved_at = now
                    row.event_streak = 0
                    row.event_started_at = None
                    row.event_consecutive_misses = 0
                    row.event_total_misses = 0
            row.event_last_processed_at = event.starts_at

    row.updated_at = now
    badge_awarded = await _award_super_streak_badge_if_needed(session, user, row, now)
    return row, badge_awarded


async def refresh_all_streaks(session: AsyncSession, *, now: datetime | None = None):
    now = now or clock.storage_utc()
    users = (await session.scalars(
        select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.id.asc())
    )).all()
    badge_notices: list[tuple[int, str]] = []
    for user in users:
        row, badge_awarded = await refresh_user_streak(session, user, now=now)
        if badge_awarded and user.tg_id:
            badge_notices.append((user.tg_id, user.full_name))
    return badge_notices


async def restore_super_streak(session: AsyncSession, user: User) -> tuple[bool, ParticipationStreak]:
    row = await get_or_create_streak(session, user.id)
    if int(row.recoverable_event_streak or 0) <= 0:
        return False, row
    if int(row.recoverable_event_streak or 0) <= int(row.event_streak or 0):
        return False, row
    row.event_streak = int(row.recoverable_event_streak or 0)
    row.event_started_at = row.recoverable_event_started_at
    row.event_consecutive_misses = 0
    row.event_total_misses = 0
    row.event_best = max(int(row.event_best or 0), int(row.event_streak or 0))
    row.recoverable_event_streak = 0
    row.recoverable_event_started_at = None
    row.recoverable_saved_at = None
    row.restores_used = int(row.restores_used or 0) + 1
    row.updated_at = clock.storage_utc()
    return True, row


async def league_counts(session: AsyncSession, season: Season) -> dict[str, int]:
    rows = await season_leaderboard_rows(session, season)
    result = {l.code: 0 for l in LEAGUES}
    for _, _, xp in rows:
        result[league_for_xp(int(xp or 0)).code] += 1
    return result
