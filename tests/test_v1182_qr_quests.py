"""v1.18.2 QR-punctuality quests: actual event scans, not manual attendance."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.domain_services import checkin_for_event, create_event, register_for_event, xp_total
from app.domain_services.quest_auto import punctuality_eligible
from app.model_domains import Quest, QuestParticipation, EventRegistration, UserRole
from app.time_utils import clock
from tests.conftest import create_user


def _quest(event, *, auto=True, grace=0, starts_at=None):
    return Quest(title="Прийди вчасно", description="Відмітка через QR-код події",
                 xp_reward=10, quest_type="individual", target_value=1,
                 completion_mode="qr_on_time" if auto else "manual",
                 event_id=event.id if auto else None, punctuality_grace_minutes=grace,
                 starts_at=starts_at or clock.storage_utc(clock.now_utc() - timedelta(hours=1)),
                 status="open", active=True)


@pytest.mark.asyncio
async def test_real_qr_checkin_awards_once_and_preserves_first_arrival(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=1182001, role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=1182002)
        start = clock.local_wall(clock.now_utc() + timedelta(minutes=25))
        event = await create_event(session, "Захід", "", start, "АМП", 15, 0, admin.id)
        quest = _quest(event)
        session.add(quest)
        await session.flush()
        await register_for_event(session, user.id, event.id)
        scan = clock.event_utc(event.starts_at) - timedelta(minutes=5)
        scanned_event, state = await checkin_for_event(session, user.id, event.checkin_token, now=scan)
        assert scanned_event.id == event.id and state == "ok"
        part = await session.scalar(select(QuestParticipation).where(
            QuestParticipation.quest_id == quest.id, QuestParticipation.user_id == user.id))
        reg = await session.scalar(select(EventRegistration).where(
            EventRegistration.event_id == event.id, EventRegistration.user_id == user.id))
        assert part.status == "approved" and part.approved_at is not None
        assert reg.status == "checked_in"  # Attendance still needs ordinary confirmation.
        assert await xp_total(session, user.id) == 10
        first_scan_at = reg.checkin_at
        second = clock.event_utc(event.starts_at) + timedelta(minutes=20)
        _event, second_state = await checkin_for_event(session, user.id, event.checkin_token, now=second)
        assert second_state == "ok"
        assert reg.checkin_at == first_scan_at
        assert await xp_total(session, user.id) == 10


@pytest.mark.asyncio
async def test_late_scan_does_not_award_qr_quest_but_records_attendance(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=1182011, role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=1182012)
        event = await create_event(session, "Подія", "", clock.local_wall(clock.now_utc() + timedelta(minutes=10)), "АМП", 15, 0, admin.id)
        quest = _quest(event, grace=0)
        session.add(quest)
        await session.flush()
        await register_for_event(session, user.id, event.id)
        _event, state = await checkin_for_event(session, user.id, event.checkin_token,
                                                 now=clock.event_utc(event.starts_at) + timedelta(minutes=1))
        assert state == "ok"
        assert await xp_total(session, user.id) == 0
        assert await session.scalar(select(QuestParticipation).where(QuestParticipation.quest_id == quest.id)) is None


@pytest.mark.asyncio
async def test_manual_quest_is_not_autocompleted_by_qr(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=1182021, role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=1182022)
        event = await create_event(session, "Подія", "", clock.local_wall(clock.now_utc() + timedelta(minutes=30)), "АМП", 15, 0, admin.id)
        quest = _quest(event, auto=False)
        session.add(quest)
        await session.flush()
        await register_for_event(session, user.id, event.id)
        _event, state = await checkin_for_event(session, user.id, event.checkin_token,
                                                 now=clock.event_utc(event.starts_at) - timedelta(minutes=5))
        assert state == "ok"
        assert await xp_total(session, user.id) == 0
        assert await session.scalar(select(QuestParticipation).where(QuestParticipation.quest_id == quest.id)) is None


def test_qr_quest_punctuality_boundaries_and_wrong_event():
    from app.model_domains import Event
    start = clock.local_wall(clock.now_utc() + timedelta(hours=1)).replace(microsecond=0)
    event = Event(id=44, title="Пунктуальність", starts_at=start)
    quest = Quest(id=55, title="Квест", event_id=44, active=True, status="open",
                  quest_type="individual", completion_mode="qr_on_time", punctuality_grace_minutes=10,
                  starts_at=clock.storage_utc(clock.now_utc() - timedelta(hours=1)))
    boundary = clock.event_utc(event.starts_at) + timedelta(minutes=10)
    assert punctuality_eligible(quest, event, boundary)
    assert not punctuality_eligible(quest, event, boundary + timedelta(microseconds=1))
    event.id = 45
    assert not punctuality_eligible(quest, event, boundary)
