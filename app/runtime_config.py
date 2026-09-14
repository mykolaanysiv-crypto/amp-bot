from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Reward, SystemSetting


@dataclass(frozen=True, slots=True)
class RuleSpec:
    key: str
    section: str
    label: str
    default: int
    minimum: int
    maximum: int
    unit: str = ""
    help: str = ""


RULE_SPECS: tuple[RuleSpec, ...] = (
    RuleSpec("xp.birthday", "xp", "XP на день народження", 20, 0, 500, "XP", "Автоматичний бонус до дня народження."),
    RuleSpec("xp.idea_approved", "xp", "XP за схвалену ідею", 10, 0, 200, "XP", "Одноразовий бонус за перше схвалення ідеї."),
    RuleSpec("xp.referral_max", "xp", "XP за запрошення", 10, 1, 200, "XP", "Максимальний бонус за перше успішне запрошення у кварталі; далі зменшується на 1 до мінімуму 1 XP."),
    RuleSpec("xp.streak_restore_cost", "xp", "Вартість відновлення серії", 100, 0, 5000, "XP", "Вартість винагороди для відновлення втраченої суперсерії."),
    RuleSpec("streak.freeze_limit_quarter", "streak", "Квартальний ліміт заморозки", 14, 0, 90, "днів", "Сумарна кількість днів заморозки серій за календарний квартал."),
    RuleSpec("streak.super_total_misses", "streak", "Пропуски суперсерії", 2, 0, 20, "подій", "Максимальна кількість пропущених подій у поточній суперсерії."),
    RuleSpec("streak.super_consecutive_misses", "streak", "Пропуски суперсерії поспіль", 1, 0, 10, "подій", "Скільки пропусків поспіль допускається до обриву суперсерії."),
    RuleSpec("streak.badge_days", "streak", "Поріг бейджа суперсерії", 30, 1, 365, "днів", "Тривалість суперсерії для автоматичного бейджа."),
    RuleSpec("events.reminder_minutes", "events", "Нагадування до події", 60, 0, 10080, "хв", "За скільки хвилин до початку надсилати нагадування."),
    RuleSpec("events.checkin_open_before_minutes", "events", "Відкрити відмітку до події", 60, 0, 1440, "хв", "За скільки хвилин до початку дозволити QR-відмітку."),
    RuleSpec("events.checkin_close_after_minutes", "events", "Закрити відмітку після старту", 360, 15, 1440, "хв", "Через скільки хвилин після початку закрити відмітку та звичайне підтвердження участі."),
    RuleSpec("events.feedback_delay_minutes", "events", "Зворотний зв’язок після події", 120, 0, 10080, "хв", "Затримка після підтвердженої участі перед запитом зворотного зв’язку."),
    RuleSpec("events.waitlist_reservation_minutes", "events", "Резерв черги очікування", 120, 5, 10080, "хв", "На скільки хвилин резервується місце після просування з черги очікування."),
    RuleSpec("privacy.suppression_threshold", "privacy", "Поріг приховування малих груп", 5, 2, 50, "осіб", "Малі чутливі групи 1…N-1 відображаються як <N."),
    RuleSpec("privacy.retention_days", "privacy", "Строк зберігання даних", 0, 0, 36500, "днів", "Політика строку зберігання. 0 = без автоматичного фізичного видалення історичних даних і записів аудиту."),
)

RULES = {spec.key: spec for spec in RULE_SPECS}
SECTIONS = {
    "xp": ("⚡ XP", "Правила автоматичних XP та вартості гейміфікації."),
    "streak": ("🔥 Серії", "Заморозки, допустимі пропуски та поріг бейджа."),
    "events": ("📅 Події", "Нагадування, вікно відмітки та підтвердження участі, зворотний зв’язок і резерв місця з черги очікування."),
    "privacy": ("🔐 Приватність", "Агрегація чутливих даних і політика зберігання."),
}


def setting_key(key: str) -> str:
    return f"runtime.{key}"


async def ensure_runtime_defaults(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(SystemSetting.key).where(SystemSetting.key.like("runtime.%")))).all())
    now = datetime.utcnow()
    for spec in RULE_SPECS:
        skey = setting_key(spec.key)
        if skey not in existing:
            session.add(SystemSetting(key=skey, value=str(spec.default), updated_at=now))
    await sync_streak_restore_reward(session)


async def get_runtime_int(session: AsyncSession, key: str, default: int | None = None) -> int:
    spec = RULES.get(key)
    fallback = spec.default if spec else int(default or 0)
    row = await session.get(SystemSetting, setting_key(key))
    if not row:
        return fallback
    try:
        value = int(float(str(row.value).strip()))
    except (TypeError, ValueError):
        return fallback
    if spec:
        return max(spec.minimum, min(spec.maximum, value))
    return value


async def get_runtime_values(session: AsyncSession) -> dict[str, int]:
    return {spec.key: await get_runtime_int(session, spec.key) for spec in RULE_SPECS}


async def set_runtime_values(session: AsyncSession, values: dict[str, Any]) -> dict[str, int]:
    now = datetime.utcnow()
    normalized: dict[str, int] = {}
    for spec in RULE_SPECS:
        raw = values.get(spec.key, spec.default)
        try:
            value = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            value = spec.default
        value = max(spec.minimum, min(spec.maximum, value))
        normalized[spec.key] = value
        skey = setting_key(spec.key)
        row = await session.get(SystemSetting, skey)
        if row:
            row.value = str(value)
            row.updated_at = now
        else:
            session.add(SystemSetting(key=skey, value=str(value), updated_at=now))
    await sync_streak_restore_reward(session, cost=normalized.get("xp.streak_restore_cost"))
    return normalized


async def sync_streak_restore_reward(session: AsyncSession, *, cost: int | None = None) -> None:
    if cost is None:
        cost = await get_runtime_int(session, "xp.streak_restore_cost")
    reward = await session.scalar(select(Reward).where(Reward.reward_type == "streak_restore").order_by(Reward.id.asc()))
    if reward:
        reward.min_xp = max(0, int(cost))
