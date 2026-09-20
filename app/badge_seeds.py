from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .model_domains import SystemSetting

BADGE_DELETE_PREFIX = "badge_seed_deleted:"


def badge_delete_setting_key(seed_key: str) -> str:
    return f"{BADGE_DELETE_PREFIX}{str(seed_key or '').strip()}"


async def badge_seed_is_deleted(session: AsyncSession, seed_key: str | None) -> bool:
    key = str(seed_key or "").strip()
    if not key:
        return False
    row = await session.get(SystemSetting, badge_delete_setting_key(key))
    return bool(row and str(row.value or "").strip() == "1")


async def mark_badge_seed_deleted(session: AsyncSession, seed_key: str | None) -> None:
    key = str(seed_key or "").strip()
    if not key:
        return
    setting_key = badge_delete_setting_key(key)
    row = await session.get(SystemSetting, setting_key)
    if row:
        row.value = "1"
    else:
        session.add(SystemSetting(key=setting_key, value="1"))
