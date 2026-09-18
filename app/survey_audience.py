from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EventRegistration, Survey, SurveyAudienceUser, User, UserStatus

SURVEY_AUDIENCE_TYPES = {"all", "users", "event"}
EVENT_AUDIENCE_STATUSES = {"registered", "reserved", "checked_in", "attended"}


def normalize_audience_type(value: str | None) -> str:
    value = (value or "all").strip().lower()
    return value if value in SURVEY_AUDIENCE_TYPES else "all"


async def eligible_user_ids(session: AsyncSession, survey: Survey) -> set[int]:
    audience_type = normalize_audience_type(getattr(survey, "audience_type", "all"))
    if audience_type == "all":
        return set((await session.scalars(
            select(User.id).where(User.status == UserStatus.ACTIVE.value)
        )).all())
    if audience_type == "users":
        return set((await session.scalars(
            select(SurveyAudienceUser.user_id).where(SurveyAudienceUser.survey_id == survey.id)
        )).all())
    event_id = getattr(survey, "audience_event_id", None)
    if not event_id:
        return set()
    return set((await session.scalars(
        select(EventRegistration.user_id).where(
            EventRegistration.event_id == event_id,
            EventRegistration.status.in_(EVENT_AUDIENCE_STATUSES),
        )
    )).all())


async def survey_available_to_user(session: AsyncSession, survey: Survey | None, user_id: int) -> bool:
    if not survey:
        return False
    audience_type = normalize_audience_type(getattr(survey, "audience_type", "all"))
    if audience_type == "all":
        return True
    if audience_type == "users":
        return bool(await session.scalar(
            select(SurveyAudienceUser.id).where(
                SurveyAudienceUser.survey_id == survey.id,
                SurveyAudienceUser.user_id == user_id,
            )
        ))
    event_id = getattr(survey, "audience_event_id", None)
    if not event_id:
        return False
    return bool(await session.scalar(
        select(EventRegistration.id).where(
            EventRegistration.event_id == event_id,
            EventRegistration.user_id == user_id,
            EventRegistration.status.in_(EVENT_AUDIENCE_STATUSES),
        )
    ))


async def eligible_users(session: AsyncSession, survey: Survey) -> list[User]:
    ids = await eligible_user_ids(session, survey)
    if not ids:
        return []
    return list((await session.scalars(
        select(User).where(
            User.id.in_(ids),
            User.status == UserStatus.ACTIVE.value,
            User.tg_id.is_not(None),
        ).order_by(User.id)
    )).all())


async def audience_summary(session: AsyncSession, survey: Survey) -> tuple[str, int]:
    audience_type = normalize_audience_type(getattr(survey, "audience_type", "all"))
    ids = await eligible_user_ids(session, survey)
    if audience_type == "users":
        return "Обрані учасники", len(ids)
    if audience_type == "event":
        return "Учасники події", len(ids)
    return "Усі активні учасники", len(ids)
