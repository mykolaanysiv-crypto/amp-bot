from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.alembic_bootstrap import downgrade, upgrade, upgrade_head
from scripts.schema_drift_check import collect_schema_diffs

PREVIOUS_PRODUCTION_HEAD = "20260921_0011"
CURRENT_HEAD = "20260921_0012"


def _url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if "amp_test" not in url:
        pytest.fail("Safety gate: full-adoption tests require a database name containing 'amp_test'")
    return url


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
    finally:
        await engine.dispose()


async def _current(url: str) -> str | None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            try:
                return await conn.scalar(text("SELECT version_num FROM alembic_version"))
            except Exception:
                return None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_alembic_upgrade_from_previous_production_schema():
    url = _url()
    await _reset(url)
    try:
        await asyncio.to_thread(upgrade, PREVIOUS_PRODUCTION_HEAD, url)
        assert await _current(url) == PREVIOUS_PRODUCTION_HEAD
        await asyncio.to_thread(upgrade_head, url)
        assert await _current(url) == CURRENT_HEAD
        assert await collect_schema_diffs(url) == []
    finally:
        await _reset(url)


@pytest.mark.asyncio
async def test_latest_revision_downgrade_upgrade_roundtrip():
    url = _url()
    await _reset(url)
    try:
        await asyncio.to_thread(upgrade_head, url)
        assert await _current(url) == CURRENT_HEAD
        await asyncio.to_thread(downgrade, PREVIOUS_PRODUCTION_HEAD, url)
        assert await _current(url) == PREVIOUS_PRODUCTION_HEAD
        await asyncio.to_thread(upgrade_head, url)
        assert await _current(url) == CURRENT_HEAD
        assert await collect_schema_diffs(url) == []
    finally:
        await _reset(url)
