from __future__ import annotations

from .time_utils import clock

from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Event, EventRegistration, User, UserRole, UserStatus
from .settlements import settlement_key


BROADCAST_TEMPLATES: dict[str, dict[str, str]] = {
    "event_reminder": {
        "title": "📅 Нагадування про подію",
        "text": (
            "📅 Нагадування про подію\n\n"
            "{first_name}, нагадуємо про найближчу активність АМП.\n\n"
            "🗓 Подія: [вкажіть назву]\n"
            "🕒 Дата і час: [вкажіть дату та час]\n"
            "📍 Місце: [вкажіть місце]\n\n"
            "До зустрічі в АМП! 🚀"
        ),
    },
    "greeting": {
        "title": "👋 Привітання",
        "text": (
            "👋 Привіт, {first_name}!\n\n"
            "Команда АМПасадорів передає тобі вітання 💙\n"
            "Дякуємо, що ти з нами, долучаєшся до активностей і розвиваєш АМП разом із нами 🚀"
        ),
    },
    "new_quest": {
        "title": "🎯 Новий квест",
        "text": (
            "🎯 Новий квест в АМП!\n\n"
            "{first_name}, для тебе вже доступний новий квест.\n"
            "Відкрий Telegram-бот → 🎯 Квести, переглянь умови та долучайся.\n\n"
            "Виконуй завдання, отримуй XP і прокачуй свій рівень 🚀"
        ),
    },
    "new_opportunity": {
        "title": "🌍 Нова можливість",
        "text": (
            "🌍 Нова можливість для молоді!\n\n"
            "{first_name}, в АМП з’явилася нова можливість для розвитку, навчання або участі.\n"
            "Відкрий Telegram-бот → 📰 Можливості та переглянь деталі.\n\n"
            "Не пропусти свій шанс 🚀"
        ),
    },
}

AUDIENCE_LABELS = {
    "all": "Усі активні учасники",
    "ambassadors": "Лише АМПасадори",
    "age_group": "Вікова група",
    "settlement": "Населений пункт",
    "event": "Учасники конкретної події",
    "inactive": "Давно не були активні",
}


def _age_on(birth_date: date, today: date | None = None) -> int:
    today = today or clock.today_local()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def personalize_message(text: str, user: User) -> str:
    """Replace safe, documented personalization tokens for one recipient."""
    first_name = (user.first_name or "").strip() or "друже"
    values = {
        "{first_name}": first_name,
        "{full_name}": user.full_name or first_name,
    }
    result = text
    for token, value in values.items():
        result = result.replace(token, value)
    return result


async def resolve_broadcast_audience(
    session: AsyncSession,
    audience_type: str,
    *,
    audience_value: str | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    inactive_days: int | None = None,
) -> list[User]:
    """Resolve an audience without exposing sensitive data in the UI.

    All communication audiences contain active profiles only. Event audiences
    exclude cancelled registrations. Inactive users are based on Telegram
    activity tracked by the bot; for older profiles without a timestamp,
    account creation time is used as a conservative fallback.
    """
    users = (await session.scalars(
        select(User)
        .where(User.status == UserStatus.ACTIVE.value)
        .order_by(User.full_name.asc())
    )).all()

    if audience_type == "all":
        return list(users)

    if audience_type == "ambassadors":
        roles = {
            UserRole.AMBASSADOR.value,
            UserRole.COORDINATOR.value,
            UserRole.ADMIN.value,
            UserRole.SUPERADMIN.value,
        }
        return [u for u in users if u.role in roles]

    if audience_type == "age_group":
        if age_min is None or age_max is None:
            return []
        low, high = sorted((int(age_min), int(age_max)))
        return [u for u in users if u.birth_date and low <= _age_on(u.birth_date) <= high]

    if audience_type == "settlement":
        target = settlement_key(audience_value)
        if not target:
            return []
        return [u for u in users if settlement_key(u.settlement) == target]

    if audience_type == "event":
        try:
            event_id = int(audience_value or "0")
        except ValueError:
            return []
        ids = set((await session.scalars(
            select(EventRegistration.user_id).where(
                EventRegistration.event_id == event_id,
                EventRegistration.status != "cancelled",
            )
        )).all())
        return [u for u in users if u.id in ids]

    if audience_type == "inactive":
        days = max(1, int(inactive_days or 30))
        cutoff = clock.storage_utc() - timedelta(days=days)
        return [u for u in users if (u.last_activity_at or u.created_at) <= cutoff]

    return []


async def audience_description(
    session: AsyncSession,
    audience_type: str,
    *,
    audience_value: str | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    inactive_days: int | None = None,
) -> str:
    if audience_type == "age_group":
        return f"Вікова група {age_min or '—'}–{age_max or '—'} років"
    if audience_type == "settlement":
        return f"Населений пункт: {audience_value or '—'}"
    if audience_type == "event":
        try:
            event = await session.get(Event, int(audience_value or "0"))
        except (TypeError, ValueError):
            event = None
        return f"Учасники події: {event.title if event else 'подію не знайдено'}"
    if audience_type == "inactive":
        return f"Не були активні {inactive_days or 30}+ днів"
    if audience_type == "system":
        return audience_value or "Системне повідомлення"
    return AUDIENCE_LABELS.get(audience_type, audience_type)


def template_options() -> list[tuple[str, str, str]]:
    return [(code, item["title"], item["text"]) for code, item in BROADCAST_TEMPLATES.items()]
