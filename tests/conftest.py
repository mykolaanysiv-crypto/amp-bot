from __future__ import annotations

from datetime import date

import pytest_asyncio

from app.config import Settings
from app.db import Database
from app.models import Season, User, UserRole, UserStatus


@pytest_asyncio.fixture
async def db(tmp_path):
    settings = Settings(
        bot_token="test-token",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        data_dir=str(tmp_path),
        media_storage="local",
        superadmin_ids=set(),
        timezone="Europe/Kyiv",
        organization_name="АМП",
        bot_name="АМПасадори",
        public_base_url="http://test",
        web_host="127.0.0.1",
        web_port=8080,
        web_admin_username="admin",
        web_admin_password="",
        web_staff_accounts={},
        web_session_secret="test-session-secret-at-least-32-chars-long",
        cookie_secure=False,
        season_name="Тестовий сезон",
        season_start=date(2026, 1, 1),
        season_end=date(2026, 12, 31),
    )
    database = Database(settings)
    await database.init()
    async with database.session_factory() as session:
        session.add(Season(name="Тестовий сезон", starts_at=date(2026, 1, 1), ends_at=date(2026, 12, 31), active=True))
        await session.commit()
    try:
        yield database
    finally:
        await database.close()


async def create_user(session, *, tg_id: int, name: str = "Тестовий Учасник", role: str = UserRole.PARTICIPANT.value, status: str = UserStatus.ACTIVE.value):
    user = User(tg_id=tg_id, full_name=name, first_name=name.split()[0], role=role, status=status, wallet_xp=0, volunteer_hours=0)
    session.add(user)
    await session.flush()
    return user
