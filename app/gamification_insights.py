from __future__ import annotations

from .time_utils import clock

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .leagues import LEAGUES, league_for_xp, runtime_leagues
from .model_domains import (
    OpportunityInterest,
    OpportunityMatch,
    Referral,
    RewardClaim,
    Season,
    SystemSetting,
    User,
    UserStatus,
    XPTransaction,
)

ENGAGEMENT_CATEGORIES = {"event", "quest", "team_quest", "activity", "task", "survey", "idea_approved"}


async def ensure_clean_data_baseline(session: AsyncSession, now: datetime | None = None) -> datetime:
    """Persist the v1.12 observation start without altering XP or rewards."""
    now = now or clock.storage_utc()
    row = await session.get(SystemSetting, "gamification.clean_data_start")
    if row and row.value:
        try:
            return datetime.fromisoformat(row.value)
        except ValueError:
            pass
    if row:
        row.value = now.isoformat(); row.updated_at = now
    else:
        session.add(SystemSetting(key="gamification.clean_data_start", value=now.isoformat(), updated_at=now))
    await session.flush()
    return now


def _rate(num: int, den: int) -> float:
    return round(num * 100.0 / den, 1) if den else 0.0


async def build_gamification_insights(session: AsyncSession, *, now: datetime | None = None) -> dict:
    leagues_runtime = await runtime_leagues(session)
    now = now or clock.storage_utc()
    baseline = await ensure_clean_data_baseline(session, now)
    observation_days = max(0, (now.date() - baseline.date()).days)
    if observation_days < 28:
        readiness = "collecting"
        readiness_label = f"Збір чистих даних: ще {28 - observation_days} дн. до першого огляду"
    elif observation_days < 56:
        readiness = "preliminary"
        readiness_label = f"Попередній аналіз доступний; до повного 8-тижневого огляду ще {56 - observation_days} дн."
    else:
        readiness = "ready"
        readiness_label = "Є щонайменше 8 тижнів чистих даних — можна готувати рішення про балансування"

    season = await session.scalar(select(Season).where(Season.active == True).order_by(Season.starts_at.desc()))  # noqa: E712
    active_users = list((await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value))).all())
    user_ids = [u.id for u in active_users]

    # The observation window starts at the persisted v1.12 baseline. Historical
    # XP still determines the league a participant starts from, but efficiency,
    # retention and transition metrics only use activity recorded after baseline.
    historical_stmt = select(XPTransaction).where(
        XPTransaction.user_id.in_(user_ids) if user_ids else False,
        XPTransaction.created_at < baseline,
    )
    tx_stmt = select(XPTransaction).where(
        XPTransaction.user_id.in_(user_ids) if user_ids else False,
        XPTransaction.created_at >= baseline,
        XPTransaction.created_at <= now,
    ).order_by(XPTransaction.user_id, XPTransaction.created_at, XPTransaction.id)
    if season:
        historical_stmt = historical_stmt.where(XPTransaction.season_id == season.id)
        tx_stmt = tx_stmt.where(XPTransaction.season_id == season.id)
    historical = list((await session.scalars(historical_stmt)).all()) if user_ids else []
    transactions = list((await session.scalars(tx_stmt)).all()) if user_ids else []

    starting_xp: Counter[int] = Counter()
    for tx in historical:
        starting_xp[tx.user_id] += int(tx.amount or 0)

    by_user: dict[int, list[XPTransaction]] = defaultdict(list)
    positive_xp = 0
    positive_actions = 0
    category_xp: Counter[str] = Counter()
    category_actions: Counter[str] = Counter()
    for tx in transactions:
        by_user[tx.user_id].append(tx)
        if int(tx.amount or 0) > 0:
            positive_xp += int(tx.amount or 0)
            positive_actions += 1
            category_xp[tx.category or "other"] += int(tx.amount or 0)
            category_actions[tx.category or "other"] += 1

    current_leagues = Counter()
    transition_counts = Counter()
    transition_days: dict[str, list[int]] = defaultdict(list)
    returning_7 = eligible_7 = returning_28 = eligible_28 = 0
    repeat_users = 0
    for user in active_users:
        rows = by_user.get(user.id, [])
        cumulative = int(starting_xp.get(user.id, 0))
        first_positive = next((r.created_at for r in rows if int(r.amount or 0) > 0 and r.category in ENGAGEMENT_CATEGORIES), None)
        # Thresholds already reached before the clean-data baseline are not
        # counted as v1.12 transitions.
        crossed: set[str] = {league.code for league in LEAGUES[1:] if cumulative >= league.min_xp}
        action_dates = [r.created_at for r in rows if int(r.amount or 0) > 0 and r.category in ENGAGEMENT_CATEGORIES]
        if len({d.date() for d in action_dates}) >= 2:
            repeat_users += 1
        for tx in rows:
            cumulative += int(tx.amount or 0)
            for league in LEAGUES[1:]:
                if cumulative >= league.min_xp and league.code not in crossed:
                    previous = LEAGUES[LEAGUES.index(league)-1]
                    key = f"{previous.code}_to_{league.code}"
                    transition_counts[key] += 1
                    if first_positive:
                        transition_days[key].append(max(0, (tx.created_at.date() - first_positive.date()).days))
                    crossed.add(league.code)
        current_leagues[league_for_xp(cumulative, leagues_runtime).code] += 1
        if first_positive:
            age_days = (now.date() - first_positive.date()).days
            if age_days >= 7:
                eligible_7 += 1
                if any((d.date() - first_positive.date()).days >= 7 for d in action_dates[1:]):
                    returning_7 += 1
            if age_days >= 28:
                eligible_28 += 1
                if any((d.date() - first_positive.date()).days >= 28 for d in action_dates[1:]):
                    returning_28 += 1

    claims = list((await session.scalars(
        select(RewardClaim).where(RewardClaim.requested_at >= baseline, RewardClaim.requested_at <= now)
    )).all())
    claimed = len(claims)
    fulfilled = sum(1 for row in claims if row.status == "fulfilled")
    xp_spent = sum(max(0, int(row.xp_spent or 0)) for row in claims if row.status in {"requested", "fulfilled"})

    matches = int(await session.scalar(select(func.count(OpportunityMatch.id)).where(
        OpportunityMatch.created_at >= baseline, OpportunityMatch.created_at <= now
    )) or 0)
    notified = int(await session.scalar(select(func.count(OpportunityMatch.id)).where(
        OpportunityMatch.notified_at.is_not(None), OpportunityMatch.notified_at >= baseline, OpportunityMatch.notified_at <= now
    )) or 0)
    interests = int(await session.scalar(select(func.count(OpportunityInterest.id)).where(
        OpportunityInterest.status == "interested", OpportunityInterest.created_at >= baseline, OpportunityInterest.created_at <= now
    )) or 0)

    referrals = list((await session.scalars(
        select(Referral).where(Referral.created_at >= baseline, Referral.created_at <= now)
    )).all())
    referral_total = len(referrals)
    referral_rewarded = sum(1 for row in referrals if row.rewarded_at is not None and row.revoked_at is None)
    invited_ids = [row.invited_user_id for row in referrals]
    referral_first_activity = 0
    if invited_ids:
        activity_users = set((await session.scalars(select(XPTransaction.user_id).where(
            XPTransaction.user_id.in_(invited_ids), XPTransaction.amount > 0,
            XPTransaction.category.in_(ENGAGEMENT_CATEGORIES), XPTransaction.created_at >= baseline, XPTransaction.created_at <= now
        ).distinct())).all())
        referral_first_activity = len(activity_users)

    league_rows = []
    for league in LEAGUES:
        league_rows.append({"code": league.code, "title": league.title, "icon": league.icon, "count": current_leagues.get(league.code, 0)})
    transitions = []
    for idx in range(len(LEAGUES)-1):
        a, b = LEAGUES[idx], LEAGUES[idx+1]
        key = f"{a.code}_to_{b.code}"
        days = transition_days.get(key, [])
        transitions.append({
            "from": a.title, "to": b.title, "count": transition_counts.get(key, 0),
            "median_days": round(float(median(days)), 1) if days else None,
        })

    category_rows = [
        {
            "category": category,
            "xp": amount,
            "actions": category_actions[category],
            "share": _rate(amount, positive_xp),
            "avg_xp": round(amount / category_actions[category], 1) if category_actions[category] else 0,
        }
        for category, amount in category_xp.most_common()
    ]

    recommendations: list[dict[str, str]] = []
    if observation_days < 28:
        recommendations.append({"level": "hold", "title": "XP не змінювати", "text": "Ще немає 4 тижнів чистої базової лінії. Збираємо дані без зміни порогів і нагород."})
    elif observation_days < 56:
        recommendations.append({"level": "watch", "title": "Лише попередні висновки", "text": "Можна аналізувати аномалії, але зміни XP краще відкласти до 8-тижневого зрізу."})
    else:
        recommendations.append({"level": "review", "title": "Можна проводити огляд балансу", "text": "Дані готові для ручного рішення. Система не змінює XP автоматично."})
    if positive_actions < 30:
        recommendations.append({"level": "hold", "title": "Мала вибірка дій", "text": f"Зафіксовано лише {positive_actions} позитивних XP-дій; порівняння категорій поки нестабільне."})
    if notified >= 10 and interests == 0:
        recommendations.append({"level": "watch", "title": "Розумні можливості", "text": "Є персональні сповіщення, але немає зафіксованих інтересів. Перевірте формулювання та CTA, не змінюючи алгоритм оцінювання."})
    if referral_total >= 5 and _rate(referral_first_activity, referral_total) < 40:
        recommendations.append({"level": "watch", "title": "Воронка запрошень", "text": "Менше 40% запрошених доходять до першої активності. Варто покращувати onboarding, а не збільшувати referral XP."})

    return {
        "generated_at": now,
        "baseline": baseline,
        "observation_days": observation_days,
        "readiness": readiness,
        "readiness_label": readiness_label,
        "season": season,
        "active_users": len(active_users),
        "league_rows": league_rows,
        "transitions": transitions,
        "retention": {
            "repeat_users": repeat_users,
            "repeat_rate": _rate(repeat_users, len(active_users)),
            "eligible_7": eligible_7, "returned_7": returning_7, "rate_7": _rate(returning_7, eligible_7),
            "eligible_28": eligible_28, "returned_28": returning_28, "rate_28": _rate(returning_28, eligible_28),
        },
        "xp": {
            "positive_xp": positive_xp, "actions": positive_actions,
            "avg_per_action": round(positive_xp / positive_actions, 1) if positive_actions else 0,
            "avg_per_active_user": round(positive_xp / len(active_users), 1) if active_users else 0,
            "categories": category_rows,
        },
        "rewards": {
            "claims": claimed, "fulfilled": fulfilled, "fulfillment_rate": _rate(fulfilled, claimed),
            "xp_spent": xp_spent, "spend_to_earned_rate": _rate(xp_spent, positive_xp),
        },
        "opportunities": {
            "matches": matches, "notified": notified, "interests": interests,
            "notify_to_interest_rate": _rate(interests, notified),
        },
        "referrals": {
            "total": referral_total, "rewarded": referral_rewarded,
            "first_activity": referral_first_activity,
            "first_activity_rate": _rate(referral_first_activity, referral_total),
            "rewarded_rate": _rate(referral_rewarded, referral_total),
        },
        "recommendations": recommendations,
    }
