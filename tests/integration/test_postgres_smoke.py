from __future__ import annotations

import os
import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import func, inspect, select

from app.config import get_settings
from app.db import Database
from app.model_domains import Base, Notification, User, UserStatus
from app.reliability import queue_notification
from app.domain_services import ensure_user_tokens
from scripts.alembic_bootstrap import upgrade_head


def _test_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if "amp_test" not in url:
        pytest.fail("Safety gate: PostgreSQL integration tests require a database name containing 'amp_test'")
    return url


@pytest.mark.asyncio
async def test_postgres_schema_and_notification_outbox(monkeypatch):
    url = _test_url()
    settings = replace(get_settings(require_bot_token=False), database_url=url)
    db = Database(settings)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await asyncio.to_thread(upgrade_head, url)
        await db.init()
        async with db.engine.begin() as conn:
            table_names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert "users" in table_names
        assert "notifications" in table_names

        async with db.session_factory() as session:
            user = User(
                tg_id=9911223344,
                full_name="CI PostgreSQL",
                first_name="CI",
                last_name="PostgreSQL",
                status=UserStatus.ACTIVE.value,
            )
            session.add(user)
            await session.flush()
            await ensure_user_tokens(session, user)
            row = await queue_notification(
                session, user.tg_id, "CI integration message", source="ci",
                recipient_user_id=user.id, dedupe_key="ci:postgres:notification",
            )
            await session.commit()
            assert row is not None
            count = int(await session.scalar(select(func.count(Notification.id))) or 0)
            assert count == 1
    finally:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await db.close()
