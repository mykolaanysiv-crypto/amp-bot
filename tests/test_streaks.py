from datetime import datetime, timedelta

from app.leagues import MAX_FREEZE_DAYS_PER_QUARTER, create_streak_freeze, freeze_days_used, get_or_create_streak, restore_super_streak
from tests.conftest import create_user


async def test_streak_freeze_quarter_limit_and_restore(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=14001)
        now = datetime(2026, 9, 13, 12, 0)
        await create_streak_freeze(session, user.id, 7, now=now, created_by_label="test")
        await create_streak_freeze(session, user.id, 7, now=now + timedelta(days=7), created_by_label="test")
        assert await freeze_days_used(session, user.id, when=now) == MAX_FREEZE_DAYS_PER_QUARTER
        streak = await get_or_create_streak(session, user.id)
        streak.recoverable_event_streak = 6
        streak.recoverable_event_started_at = now - timedelta(days=40)
        ok, streak = await restore_super_streak(session, user)
        assert ok is True
        assert streak.event_streak == 6
        assert streak.recoverable_event_streak == 0
