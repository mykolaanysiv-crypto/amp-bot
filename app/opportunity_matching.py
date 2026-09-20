from __future__ import annotations

from .time_utils import clock

import json
import logging
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .model_domains import Opportunity, OpportunityMatch, User, UserStatus
from .observability import log_extra
from .domain_services import age_on
from .settlements import settlement_key

OPPORTUNITY_INTERESTS: tuple[str, ...] = (
    "Волонтерство", "Освіта", "Гранти", "Обміни", "Підприємництво",
    "Культура", "Спорт", "IT", "Медіа",
)

_CATEGORY_ALIASES = {
    "волонтер": "Волонтерство", "volunteer": "Волонтерство",
    "освіт": "Освіта", "навчан": "Освіта", "курс": "Освіта",
    "грант": "Гранти", "fund": "Гранти",
    "обмін": "Обміни", "exchange": "Обміни", "erasmus": "Обміни",
    "підприєм": "Підприємництво", "бізнес": "Підприємництво", "startup": "Підприємництво",
    "культур": "Культура", "мистец": "Культура",
    "спорт": "Спорт", "фітнес": "Спорт",
    "it": "IT", "айті": "IT", "програм": "IT", "цифров": "IT",
    "медіа": "Медіа", "smm": "Медіа", "контент": "Медіа", "журналіст": "Медіа",
}


def user_interests(user: User) -> list[str]:
    raw = user.opportunity_interests_json or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if x in OPPORTUNITY_INTERESTS]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logging.getLogger("amp.opportunity_matching").debug(
            "Legacy opportunity interests are not JSON; using CSV fallback",
            extra=log_extra("OPPORTUNITY_INTERESTS_JSON_FALLBACK", exception_type=type(exc).__name__),
        )
    return [x.strip() for x in raw.split(",") if x.strip() in OPPORTUNITY_INTERESTS]


def set_user_interests(user: User, interests: Iterable[str]) -> list[str]:
    cleaned = [x for x in OPPORTUNITY_INTERESTS if x in set(interests)]
    user.opportunity_interests_json = json.dumps(cleaned, ensure_ascii=False)
    return cleaned


def opportunity_category(item: Opportunity) -> str | None:
    haystack = " ".join([item.direction or "", item.kind or "", item.title or "", item.description or ""]).lower()
    # exact canonical names first
    for category in OPPORTUNITY_INTERESTS:
        if category.lower() in haystack:
            return category
    for token, category in _CATEGORY_ALIASES.items():
        if token in haystack:
            return category
    return None


def _target_settlements(item: Opportunity) -> list[str]:
    raw = (item.target_settlements or "").strip()
    if not raw:
        return []
    return [settlement_key(x) for x in raw.replace(";", ",").split(",") if x.strip()]


def match_opportunity(user: User, item: Opportunity, *, now: datetime | None = None) -> tuple[int, list[str]] | None:
    """Privacy-preserving match. Vulnerability/social categories are intentionally not read."""
    now = now or clock.storage_utc()
    if not item.active or (item.deadline and item.deadline < now):
        return None

    reasons: list[str] = []
    score = 0

    if user.birth_date:
        age = age_on(user.birth_date, now.date())
        if item.age_min is not None and age < item.age_min:
            return None
        if item.age_max is not None and age > item.age_max:
            return None
        if item.age_min is not None or item.age_max is not None:
            score += 20; reasons.append("вік")

    interests = user_interests(user)
    category = opportunity_category(item)
    if interests:
        if category and category in interests:
            score += 50; reasons.append(category)
        elif category:
            return None
        else:
            score += 10; reasons.append("загальна можливість")
    else:
        # Without an explicit preference we keep the catalogue available, but
        # do not auto-profile/notify until the participant chooses interests.
        return None

    targets = _target_settlements(item)
    if targets:
        settlement = settlement_key(user.settlement)
        wildcard = any(x in {"усі", "всі", "all", "будь-який", "будь-яка"} for x in targets)
        if not wildcard and settlement not in targets:
            # Online opportunities are still reachable regardless of village.
            fmt = (item.format or "").casefold()
            if "онлайн" not in fmt and "online" not in fmt and "гібр" not in fmt:
                return None
        if wildcard or settlement in targets:
            score += 15; reasons.append("населений пункт")
    else:
        score += 5

    fmt = (item.format or "").casefold()
    if "онлайн" in fmt or "online" in fmt:
        score += 10; reasons.append("онлайн")
    elif "гібр" in fmt:
        score += 8; reasons.append("гібрид")
    else:
        score += 5

    if item.deadline:
        days = max(0, (item.deadline - now).days)
        if days <= 3:
            score += 3; reasons.append("дедлайн скоро")
        elif days <= 14:
            score += 6
        else:
            score += 8
    else:
        score += 8

    return min(100, score), reasons


async def refresh_matches_for_opportunity(session: AsyncSession, item: Opportunity) -> int:
    users = list((await session.scalars(select(User).where(
        User.status == UserStatus.ACTIVE.value,
        User.tg_id.is_not(None),
    ))).all())
    matched = 0
    for user in users:
        result = match_opportunity(user, item)
        existing = await session.scalar(select(OpportunityMatch).where(
            OpportunityMatch.opportunity_id == item.id,
            OpportunityMatch.user_id == user.id,
        ))
        if not result:
            if existing:
                existing.status = "stale"
                existing.updated_at = clock.storage_utc()
            continue
        score, reasons = result
        if existing:
            existing.score = score
            existing.reasons_json = json.dumps(reasons, ensure_ascii=False)
            existing.status = "notified" if existing.notified_at else "matched"
            existing.updated_at = clock.storage_utc()
        else:
            session.add(OpportunityMatch(
                opportunity_id=item.id, user_id=user.id, score=score,
                reasons_json=json.dumps(reasons, ensure_ascii=False), status="matched",
            ))
        matched += 1
    return matched


async def refresh_matches_for_user(session: AsyncSession, user: User) -> int:
    now = clock.storage_utc()
    rows = list((await session.scalars(select(Opportunity).where(
        Opportunity.active == True,  # noqa: E712
        (Opportunity.deadline.is_(None)) | (Opportunity.deadline >= now),
    ))).all())
    count = 0
    for item in rows:
        result = match_opportunity(user, item, now=now)
        existing = await session.scalar(select(OpportunityMatch).where(
            OpportunityMatch.opportunity_id == item.id,
            OpportunityMatch.user_id == user.id,
        ))
        if not result:
            if existing:
                existing.status = "stale"
                existing.updated_at = clock.storage_utc()
            continue
        score, reasons = result
        if existing:
            existing.score = score; existing.reasons_json = json.dumps(reasons, ensure_ascii=False); existing.status = "notified" if existing.notified_at else "matched"; existing.updated_at = now
        else:
            session.add(OpportunityMatch(opportunity_id=item.id, user_id=user.id, score=score, reasons_json=json.dumps(reasons, ensure_ascii=False)))
        count += 1
    return count


async def queue_pending_match_digests(session: AsyncSession, *, max_items: int = 3) -> int:
    """Queue one digest per user and mark the matched rows notified atomically."""
    from .reliability import queue_notification
    now = clock.storage_utc()
    user_ids = list((await session.scalars(
        select(OpportunityMatch.user_id)
        .join(Opportunity, Opportunity.id == OpportunityMatch.opportunity_id)
        .join(User, User.id == OpportunityMatch.user_id)
        .where(
            OpportunityMatch.notified_at.is_(None),
            OpportunityMatch.status == "matched",
            Opportunity.active == True,  # noqa: E712
            User.status == UserStatus.ACTIVE.value,
            (Opportunity.deadline.is_(None)) | (Opportunity.deadline >= now),
        ).distinct()
    )).all())
    queued = 0
    for user_id in user_ids:
        user = await session.get(User, int(user_id))
        if not user or not user.tg_id:
            continue
        rows = (await session.execute(
            select(OpportunityMatch, Opportunity)
            .join(Opportunity, Opportunity.id == OpportunityMatch.opportunity_id)
            .where(
                OpportunityMatch.user_id == user.id,
                OpportunityMatch.notified_at.is_(None),
                OpportunityMatch.status == "matched",
                Opportunity.active == True,  # noqa: E712
                (Opportunity.deadline.is_(None)) | (Opportunity.deadline >= now),
            )
            .order_by(OpportunityMatch.score.desc(), Opportunity.deadline.asc().nullslast())
            .limit(max_items)
        )).all()
        if not rows:
            continue
        count = len(rows)
        noun = "нову можливість" if count == 1 else "нові можливості" if 2 <= count <= 4 else "нових можливостей"
        lines = [f"🌍 <b>Для тебе знайдено {count} {noun}</b>", ""]
        ids: list[int] = []
        for idx, (match, item) in enumerate(rows, 1):
            ids.append(item.id)
            deadline = item.deadline.strftime("%d.%m.%Y") if item.deadline else "без дедлайну"
            lines.append(f"{idx}. <b>{item.title}</b> · {deadline}")
        lines.append("\nВідкрий «🌍 Можливості» — список автоматично впорядковано за актуальністю та дедлайном.")
        key = f"smart_opportunities:{user.id}:" + ",".join(map(str, ids))
        await queue_notification(
            session, user.tg_id, "\n".join(lines), source="opportunity_match",
            notification_type="system", title="Персональні можливості",
            recipient_user_id=user.id, entity_type="opportunity_match",
            dedupe_key=key, button_text="🌍 Відкрити можливості", callback_data="nav:opportunities",
        )
        for match, _ in rows:
            match.notified_at = now; match.status = "notified"; match.updated_at = now
        queued += 1
    return queued
