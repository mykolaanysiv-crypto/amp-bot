from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .leagues import LEAGUES, league_for_xp
from .models import (
    Badge, Event, EventRegistration, Season, User, UserBadge,
    VolunteerTask, VolunteerTaskParticipation, XPTransaction,
)


def _longest_week_streak(dates: list[datetime]) -> int:
    if not dates:
        return 0
    weeks = sorted({(d.date() - timedelta(days=d.weekday())) for d in dates})
    best = cur = 1
    for prev, nxt in zip(weeks, weeks[1:]):
        if (nxt - prev).days == 7:
            cur += 1
        else:
            cur = 1
        best = max(best, cur)
    return best


async def build_season_snapshot(session: AsyncSession, season: Season) -> dict:
    start = datetime.combine(season.starts_at, datetime.min.time())
    end = datetime.combine(season.ends_at, datetime.max.time())

    xp_rows = (await session.execute(
        select(User.id, User.full_name, User.role, func.coalesce(func.sum(XPTransaction.amount), 0).label("xp"))
        .join(XPTransaction, XPTransaction.user_id == User.id)
        .where(XPTransaction.season_id == season.id)
        .group_by(User.id, User.full_name, User.role)
        .order_by(func.sum(XPTransaction.amount).desc(), User.full_name.asc())
    )).all()
    leaderboard = [
        {"user_id": int(uid), "name": name, "role": role, "xp": int(xp or 0)}
        for uid, name, role, xp in xp_rows
    ]

    league_winners = []
    by_league: dict[str, list[dict]] = {lg.code: [] for lg in LEAGUES}
    for row in leaderboard:
        by_league[league_for_xp(row["xp"]).code].append(row)
    for lg in LEAGUES:
        rows = by_league[lg.code]
        if rows:
            league_winners.append({"league": lg.title, "icon": lg.icon, **rows[0]})

    # Season-specific weekly streak from actual XP activity dates.
    tx_rows = (await session.execute(
        select(XPTransaction.user_id, XPTransaction.created_at)
        .where(
            XPTransaction.season_id == season.id,
            XPTransaction.amount > 0,
            XPTransaction.created_at >= start,
            XPTransaction.created_at <= end,
        )
    )).all()
    tx_by_user: dict[int, list[datetime]] = {}
    for uid, created in tx_rows:
        if created:
            tx_by_user.setdefault(int(uid), []).append(created)
    streak_records = []
    name_map = {int(r["user_id"]): r["name"] for r in leaderboard}
    for uid, dates in tx_by_user.items():
        streak_records.append({"user_id": uid, "name": name_map.get(uid, f"АМП-{uid:04d}"), "weeks": _longest_week_streak(dates)})
    streak_records.sort(key=lambda x: (-x["weeks"], x["name"]))

    event_hours = (await session.execute(
        select(EventRegistration.user_id, func.coalesce(func.sum(Event.volunteer_hours), 0))
        .join(Event, Event.id == EventRegistration.event_id)
        .where(
            EventRegistration.status == "attended",
            EventRegistration.confirmed_at >= start,
            EventRegistration.confirmed_at <= end,
        ).group_by(EventRegistration.user_id)
    )).all()
    task_hours = (await session.execute(
        select(VolunteerTaskParticipation.user_id, func.coalesce(func.sum(VolunteerTask.hours_reward), 0))
        .join(VolunteerTask, VolunteerTask.id == VolunteerTaskParticipation.task_id)
        .where(
            VolunteerTaskParticipation.status == "approved",
            VolunteerTaskParticipation.approved_at >= start,
            VolunteerTaskParticipation.approved_at <= end,
        ).group_by(VolunteerTaskParticipation.user_id)
    )).all()
    hours: dict[int, float] = {}
    for uid, value in list(event_hours) + list(task_hours):
        hours[int(uid)] = hours.get(int(uid), 0.0) + float(value or 0)
    hour_records = [{"user_id": uid, "name": name_map.get(uid, f"АМП-{uid:04d}"), "hours": round(value, 2)} for uid, value in hours.items()]
    hour_records.sort(key=lambda x: (-x["hours"], x["name"]))

    badge_rows = (await session.execute(
        select(Badge.name, func.count(UserBadge.id))
        .join(UserBadge, UserBadge.badge_id == Badge.id)
        .where(UserBadge.awarded_at >= start, UserBadge.awarded_at <= end)
        .group_by(Badge.name).order_by(func.count(UserBadge.id).desc(), Badge.name.asc())
    )).all()
    badge_summary = [{"name": name, "count": int(count or 0)} for name, count in badge_rows]
    badges_count = sum(row["count"] for row in badge_summary)
    participants = len({int(uid) for uid, _ in (await session.execute(select(XPTransaction.user_id, func.count(XPTransaction.id)).where(XPTransaction.season_id == season.id).group_by(XPTransaction.user_id))).all()})
    total_xp = sum(r["xp"] for r in leaderboard)

    return {
        "season_id": season.id,
        "name": season.name,
        "period": {"starts_at": season.starts_at.isoformat(), "ends_at": season.ends_at.isoformat()},
        "top3": leaderboard[:3],
        "league_winners": league_winners,
        "records": {
            "xp": leaderboard[0] if leaderboard else None,
            "streak": streak_records[0] if streak_records else None,
            "volunteer_hours": hour_records[0] if hour_records else None,
        },
        "stats": {
            "participants": participants,
            "total_xp": total_xp,
            "badges_awarded": badges_count,
            "badges": badge_summary,
            "league_distribution": {lg.title: len(by_league[lg.code]) for lg in LEAGUES},
        },
        "leaderboard": leaderboard,
        "created_at": datetime.utcnow().isoformat(),
    }


async def finalize_season(session: AsyncSession, season: Season, *, force: bool = False) -> dict:
    if season.history_json and season.finalized_at and not force:
        try:
            return json.loads(season.history_json)
        except Exception:
            pass
    snapshot = await build_season_snapshot(session, season)
    season.history_json = json.dumps(snapshot, ensure_ascii=False)
    season.finalized_at = datetime.utcnow()
    season.active = False
    season.archived = True
    return snapshot


def season_snapshot(season: Season) -> dict | None:
    if not season.history_json:
        return None
    try:
        data = json.loads(season.history_json)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def user_season_history(session: AsyncSession, user_id: int) -> list[dict]:
    seasons = list((await session.scalars(select(Season).order_by(Season.starts_at.desc()))).all())
    result: list[dict] = []
    for season in seasons:
        xp = int(await session.scalar(select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(XPTransaction.user_id == user_id, XPTransaction.season_id == season.id)) or 0)
        if xp <= 0 and not season.active:
            continue
        ranking = (await session.execute(
            select(XPTransaction.user_id, func.coalesce(func.sum(XPTransaction.amount), 0).label("xp"))
            .where(XPTransaction.season_id == season.id)
            .group_by(XPTransaction.user_id)
            .order_by(func.sum(XPTransaction.amount).desc())
        )).all()
        rank = next((i for i, (uid, _) in enumerate(ranking, 1) if int(uid) == int(user_id)), None)
        result.append({
            "id": season.id, "name": season.name, "xp": xp, "rank": rank,
            "league": league_for_xp(xp), "active": season.active, "archived": season.archived,
            "starts_at": season.starts_at, "ends_at": season.ends_at,
        })
    return result
