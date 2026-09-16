from __future__ import annotations

from .time_utils import clock

import json
from datetime import datetime

from sqlalchemy import select

from .gamification import normalize_quest_xp, normalize_task_xp
from .models import (
    Idea,
    Quest,
    QuestParticipation,
    Survey,
    SurveyResponse,
    User,
    VolunteerTask,
    VolunteerTaskParticipation,
)
from .runtime_config import get_runtime_int
from .services import add_xp, evaluate_automatic_badges


async def approve_quest_participation(
    session,
    quest: Quest,
    participation: QuestParticipation,
    user: User,
    *,
    created_by: int | None = None,
):
    """Approve a completed individual quest and award XP exactly once."""
    if participation.status != "completed":
        return None
    quest.xp_reward = normalize_quest_xp(quest.xp_reward, quest.quest_type)
    total, level, leveled = await add_xp(
        session,
        user,
        quest.xp_reward,
        f"Квест «{quest.title}»",
        category="quest",
        created_by=created_by,
    )
    participation.status = "approved"
    participation.approved_at = clock.storage_utc()
    await evaluate_automatic_badges(session, user)
    return total, level, leveled


async def approve_volunteer_task_participation(
    session,
    task: VolunteerTask,
    participation: VolunteerTaskParticipation,
    user: User,
    *,
    admin_note: str = "",
    created_by: int | None = None,
):
    """Approve a submitted volunteer task and award XP/hours exactly once."""
    if participation.status != "submitted":
        return None
    task.xp_reward = normalize_task_xp(task.xp_reward, task.hours_reward)
    total, level, leveled = await add_xp(
        session,
        user,
        task.xp_reward,
        f"Волонтерська задача «{task.title}»",
        category="task",
        created_by=created_by,
    )
    user.volunteer_hours += float(task.hours_reward or 0)
    participation.status = "approved"
    participation.approved_at = clock.storage_utc()
    participation.admin_note = (admin_note or "").strip()
    await evaluate_automatic_badges(session, user)
    return total, level, leveled


def survey_is_available(survey: Survey, *, now: datetime | None = None) -> bool:
    now = now or clock.storage_utc()
    if survey.status != "published":
        return False
    if survey.starts_at and survey.starts_at > now:
        return False
    if survey.ends_at and survey.ends_at < now:
        return False
    return True


async def complete_survey_once(
    session,
    survey: Survey,
    user: User,
    answers: dict,
) -> tuple[SurveyResponse | None, int, str]:
    """Persist one response and award survey XP once per participant."""
    existing = await session.scalar(
        select(SurveyResponse).where(
            SurveyResponse.survey_id == survey.id,
            SurveyResponse.user_id == user.id,
        )
    )
    if existing:
        return existing, 0, "already_completed"
    if not survey_is_available(survey):
        return None, 0, "closed"
    reward = max(0, int(survey.xp_reward or 0))
    response = SurveyResponse(
        survey_id=survey.id,
        user_id=user.id,
        answers_json=json.dumps(answers, ensure_ascii=False),
        xp_awarded=reward,
    )
    session.add(response)
    await session.flush()
    if reward:
        await add_xp(
            session,
            user,
            reward,
            f"Пройдено опитування: {survey.title}",
            category="survey",
        )
    return response, reward, "completed"


async def award_idea_approval_once(session, idea: Idea) -> tuple[int | None, str]:
    """Award the configured idea-approval XP bonus only once."""
    if idea.approval_xp_awarded_at:
        return None, ""
    author = await session.get(User, idea.user_id)
    if not author:
        return None, ""
    reward = await get_runtime_int(session, "xp.idea_approved")
    total, level, leveled = await add_xp(
        session,
        author,
        reward,
        f"Схвалена ідея «{idea.title}»",
        category="idea_approved",
    )
    idea.approval_xp_awarded_at = clock.storage_utc()
    text = (
        f"💡 <b>Вашу ідею «{idea.title}» схвалено!</b>\n"
        f"⚡ За схвалену ідею нараховано <b>+{reward} XP</b>.\n"
        f"Загальний досвід: <b>{total} XP</b>"
    )
    if leveled:
        text += f"\n🎉 Новий рівень: <b>{level}</b>"
    return author.tg_id, text
