from __future__ import annotations

from .time_utils import clock

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .runtime_config import get_runtime_int
from .models import (
    ActivityApplication, Event, EventRegistration, Goal, Idea, Opportunity, Quest, Survey, SurveyResponse,
    QuestParticipation, Referral, User, UserBadge, UserRole, UserStatus, VolunteerTask,
    VolunteerTaskParticipation, XPTransaction, GoalReward, ParticipationStreak,
)

AMBASSADOR_ROLES = {UserRole.AMBASSADOR.value, UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value}
GOAL_METRIC_LABELS = {
    "xp": "XP",
    "visits": "відвідувань",
    "hours": "волонтерських годин",
    "quests": "виконаних квестів",
    "activities": "підтверджених активностей",
    "ideas": "реалізованих ідей",
    "tasks": "волонтерських задач",
    "surveys": "пройдених опитувань",
    "badges": "отриманих бейджів",
    "referrals": "успішних запрошень",
    "weekly_streak": "тижнів активної серії",
    "event_streak": "подій суперсерії",
}


def _month_key(value: datetime | date | None) -> tuple[int, int] | None:
    return (value.year, value.month) if value else None


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


async def active_month_streak(session: AsyncSession, user_id: int, *, now: datetime | None = None) -> int:
    now = now or clock.storage_utc()
    months: set[tuple[int, int]] = set()
    queries = [
        select(XPTransaction.created_at).where(XPTransaction.user_id == user_id, XPTransaction.amount > 0),
        select(EventRegistration.confirmed_at).where(EventRegistration.user_id == user_id, EventRegistration.status == "attended"),
        select(QuestParticipation.approved_at).where(QuestParticipation.user_id == user_id, QuestParticipation.status == "approved"),
        select(VolunteerTaskParticipation.approved_at).where(VolunteerTaskParticipation.user_id == user_id, VolunteerTaskParticipation.status == "approved"),
        select(ActivityApplication.completed_at).where(ActivityApplication.user_id == user_id, ActivityApplication.status == "activity_completed"),
    ]
    for stmt in queries:
        for value in (await session.scalars(stmt)).all():
            key = _month_key(value)
            if key:
                months.add(key)
    year, month = now.year, now.month
    streak = 0
    while (year, month) in months:
        streak += 1
        year, month = _previous_month(year, month)
    return streak


def _goal_window(goal: Goal, now: datetime) -> tuple[datetime, datetime]:
    return goal.starts_at or datetime.min, min(goal.ends_at or now, now)


async def _goal_user_ids(session: AsyncSession, goal: Goal, current_user: User | None) -> list[int]:
    """Resolve the people whose activity is measured for a goal.

    Season missions are intentionally personal when rendered for a participant:
    each person sees their own progress.  The web admin overview may pass
    current_user=None to see the combined community progress.  Team goals are
    always measured collectively for active Ambassador-team roles.
    """
    if goal.scope == "personal":
        return [goal.user_id] if goal.user_id else ([current_user.id] if current_user else [])
    if goal.scope == "team":
        return list((await session.scalars(
            select(User.id).where(User.status == UserStatus.ACTIVE.value, User.role.in_(AMBASSADOR_ROLES))
        )).all())
    if current_user is not None:
        return [current_user.id]
    return list((await session.scalars(
        select(User.id).where(User.status == UserStatus.ACTIVE.value)
    )).all())


async def goal_progress(session: AsyncSession, goal: Goal, current_user: User | None = None, *, now: datetime | None = None) -> float:
    now = now or clock.storage_utc()
    start, end = _goal_window(goal, now)
    user_ids = await _goal_user_ids(session, goal, current_user)
    if not user_ids:
        return 0.0
    if goal.metric == "xp":
        return float(await session.scalar(select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(XPTransaction.user_id.in_(user_ids), XPTransaction.amount > 0, XPTransaction.created_at >= start, XPTransaction.created_at <= end)) or 0)
    if goal.metric == "visits":
        return float(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.user_id.in_(user_ids), EventRegistration.status == "attended", EventRegistration.confirmed_at >= start, EventRegistration.confirmed_at <= end)) or 0)
    if goal.metric == "quests":
        return float(await session.scalar(select(func.count(QuestParticipation.id)).where(QuestParticipation.user_id.in_(user_ids), QuestParticipation.status == "approved", QuestParticipation.approved_at >= start, QuestParticipation.approved_at <= end)) or 0)
    if goal.metric == "activities":
        return float(await session.scalar(select(func.count(ActivityApplication.id)).where(ActivityApplication.user_id.in_(user_ids), ActivityApplication.status == "activity_completed", ActivityApplication.completed_at >= start, ActivityApplication.completed_at <= end)) or 0)
    if goal.metric == "ideas":
        return float(await session.scalar(select(func.count(Idea.id)).where(Idea.user_id.in_(user_ids), Idea.status == "implemented", Idea.updated_at >= start, Idea.updated_at <= end)) or 0)
    if goal.metric == "tasks":
        return float(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.user_id.in_(user_ids), VolunteerTaskParticipation.status == "approved", VolunteerTaskParticipation.approved_at >= start, VolunteerTaskParticipation.approved_at <= end)) or 0)
    if goal.metric == "surveys":
        return float(await session.scalar(select(func.count(SurveyResponse.id)).where(SurveyResponse.user_id.in_(user_ids), SurveyResponse.completed_at >= start, SurveyResponse.completed_at <= end)) or 0)
    if goal.metric == "badges":
        return float(await session.scalar(select(func.count(UserBadge.id)).where(UserBadge.user_id.in_(user_ids), UserBadge.awarded_at >= start, UserBadge.awarded_at <= end)) or 0)
    if goal.metric == "referrals":
        return float(await session.scalar(select(func.count(Referral.id)).where(Referral.inviter_user_id.in_(user_ids), Referral.status == "rewarded", Referral.rewarded_at.is_not(None), Referral.rewarded_at >= start, Referral.rewarded_at <= end)) or 0)
    if goal.metric in {"weekly_streak", "event_streak"}:
        rows = list((await session.scalars(select(ParticipationStreak).where(ParticipationStreak.user_id.in_(user_ids)))).all())
        field = "weekly_streak" if goal.metric == "weekly_streak" else "event_streak"
        return float(sum(int(getattr(row, field, 0) or 0) for row in rows))
    if goal.metric == "hours":
        event_hours = float(await session.scalar(select(func.coalesce(func.sum(Event.volunteer_hours), 0)).select_from(EventRegistration).join(Event, Event.id == EventRegistration.event_id).where(EventRegistration.user_id.in_(user_ids), EventRegistration.status == "attended", EventRegistration.confirmed_at >= start, EventRegistration.confirmed_at <= end)) or 0)
        task_hours = float(await session.scalar(select(func.coalesce(func.sum(VolunteerTask.hours_reward), 0)).select_from(VolunteerTaskParticipation).join(VolunteerTask, VolunteerTask.id == VolunteerTaskParticipation.task_id).where(VolunteerTaskParticipation.user_id.in_(user_ids), VolunteerTaskParticipation.status == "approved", VolunteerTaskParticipation.approved_at >= start, VolunteerTaskParticipation.approved_at <= end)) or 0)
        activity_hours = float(await session.scalar(select(func.coalesce(func.sum(ActivityApplication.hours_reward), 0)).where(ActivityApplication.user_id.in_(user_ids), ActivityApplication.status == "activity_completed", ActivityApplication.completed_at >= start, ActivityApplication.completed_at <= end)) or 0)
        return round(event_hours + task_hours + activity_hours, 2)
    return 0.0


async def goals_for_user(session: AsyncSession, user: User, *, now: datetime | None = None) -> list[dict]:
    now = now or clock.storage_utc()
    goals = list((await session.scalars(select(Goal).where(Goal.active == True).order_by(Goal.scope.asc(), Goal.ends_at.asc().nullslast(), Goal.id.desc()))).all())  # noqa: E712
    result: list[dict] = []
    for goal in goals:
        if goal.ends_at and goal.ends_at < now:
            continue
        if goal.scope == "personal" and goal.user_id != user.id:
            continue
        if goal.scope == "team" and user.role not in AMBASSADOR_ROLES:
            continue
        progress = await goal_progress(session, goal, user, now=now)
        target = max(float(goal.target_value or 0), 0.0)
        percent = min(100.0, (progress / target * 100.0) if target else 100.0)
        result.append({"goal":goal, "progress":progress, "target":target, "percent":round(percent,1), "metric_label":GOAL_METRIC_LABELS.get(goal.metric, goal.metric)})
    return result


async def process_goal_rewards(session: AsyncSession, *, now: datetime | None = None) -> list[tuple[int, str, int]]:
    """Award configured XP once when goals are completed.

    Returns ``(tg_id, goal_title, reward_xp)`` rows so the caller can notify
    participants after the transaction is committed.  GoalReward's unique
    constraint makes repeated scheduler runs idempotent.
    """
    from .services import add_xp

    now = now or clock.storage_utc()
    goals = list((await session.scalars(
        select(Goal).where(Goal.active == True, Goal.reward_xp > 0)  # noqa: E712
        .order_by(Goal.id.asc())
    )).all())
    notices: list[tuple[int, str, int]] = []

    for goal in goals:
        # A future mission cannot be completed before it starts.  Expired goals
        # are still checked once using their fixed end boundary, so a scheduler
        # tick immediately after the deadline does not lose a legitimate reward.
        if goal.starts_at and goal.starts_at > now:
            continue

        recipients: list[User] = []
        if goal.scope == "personal":
            if goal.user_id:
                u = await session.get(User, goal.user_id)
                if u and u.status == UserStatus.ACTIVE.value:
                    recipients = [u]
        elif goal.scope == "team":
            team_users = list((await session.scalars(
                select(User).where(User.status == UserStatus.ACTIVE.value, User.role.in_(AMBASSADOR_ROLES))
                .order_by(User.id.asc())
            )).all())
            team_progress = await goal_progress(session, goal, None, now=now)
            if team_progress >= float(goal.target_value or 0):
                recipients = team_users
        else:  # season: individual progress toward one shared mission definition
            recipients = list((await session.scalars(
                select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.id.asc())
            )).all())

        for user in recipients:
            if goal.scope != "team":
                progress = await goal_progress(session, goal, user, now=now)
                if progress < float(goal.target_value or 0):
                    continue
            exists = await session.scalar(select(GoalReward.id).where(
                GoalReward.goal_id == goal.id, GoalReward.user_id == user.id
            ))
            if exists:
                continue
            await add_xp(
                session, user, int(goal.reward_xp),
                f"Виконано ціль/місію «{goal.title}»",
                category="goal_reward",
            )
            session.add(GoalReward(
                goal_id=goal.id, user_id=user.id, xp_awarded=int(goal.reward_xp), awarded_at=now
            ))
            notices.append((user.tg_id, goal.title, int(goal.reward_xp)))
    return notices


async def process_expired_content(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    # Operational timestamps are UTC; scheduled content deadlines are legacy
    # Europe/Kyiv local-wall values. Normalize the instant once, then convert
    # each scheduled boundary to aware UTC before making lifecycle decisions.
    if now is None:
        now_utc = clock.now_utc()
    elif now.tzinfo is None:
        # Legacy callers historically passed a naive UTC operational timestamp.
        now_utc = clock.from_storage_utc(now) or clock.now_utc()
    else:
        now_utc = clock.ensure_utc(now)
    storage_now = clock.storage_utc(now_utc)

    changed = defaultdict(int)
    events = list((await session.scalars(select(Event).where(Event.status.in_(["open", "closed", "postponed"]), Event.cancelled_at.is_(None)))).all())
    checkin_close_minutes = await get_runtime_int(session, "events.checkin_close_after_minutes")
    for event in events:
        # No explicit end-time exists, so the configured attendance window also
        # defines when the event moves to completed.
        event_start_utc = clock.event_utc(event.starts_at)
        if event_start_utc and event_start_utc + timedelta(minutes=checkin_close_minutes) < now_utc:
            event.status = "completed"; changed["events"] += 1
    quests = list((await session.scalars(select(Quest).where(Quest.status.in_(["open", "postponed"]), Quest.cancelled_at.is_(None)))).all())
    for quest in quests:
        if quest.ends_at and clock.local_wall_to_utc(quest.ends_at) < now_utc:
            quest.active = False
            # ``Quest.completed`` is reserved for the team-goal reward flow.
            # The deadline lifecycle is represented by ``status=completed`` only.
            quest.status = "completed"
            changed["quests"] += 1
    tasks = list((await session.scalars(select(VolunteerTask).where(VolunteerTask.status.in_(["open", "active", "postponed"]), VolunteerTask.cancelled_at.is_(None)))).all())
    for task in tasks:
        if task.deadline and clock.local_wall_to_utc(task.deadline) < now_utc:
            task.status = "completed"; changed["tasks"] += 1
    surveys = list((await session.scalars(
        select(Survey).where(Survey.status == "published", Survey.ends_at.is_not(None))
    )).all())
    for survey in surveys:
        if survey.ends_at and clock.local_wall_to_utc(survey.ends_at) < now_utc:
            survey.status = "closed"
            survey.updated_at = storage_now
            changed["surveys"] += 1

    opportunities = list((await session.scalars(select(Opportunity).where(Opportunity.active == True))).all())  # noqa: E712
    for item in opportunities:
        if item.deadline and clock.local_wall_to_utc(item.deadline) < now_utc:
            item.active = False; item.updated_at = storage_now; changed["opportunities"] += 1
    return dict(changed)
