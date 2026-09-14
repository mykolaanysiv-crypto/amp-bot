from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.models import EventRegistration, UserRole
from app.reports import build_period_report, resolve_report_period
from app.services import (
    checkin_for_event,
    confirm_single_event_attendance,
    create_event,
    event_checkin_window,
    register_for_event,
    xp_total,
)
from app.settlements import ensure_settlement_directory, settlement_quality_report
from tests.conftest import create_user


async def _event(session, admin, *, starts_at: datetime, title: str = "P0 подія"):
    return await create_event(session, title, "", starts_at, "АМП", 20, 1.5, admin.id)


async def test_checkin_day_before_is_blocked_without_mutation(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21001, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21002)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now + timedelta(days=1))
        reg = await register_for_event(session, user.id, event.id)

        checked_event, state = await checkin_for_event(session, user.id, event.checkin_token, now=now)

        assert checked_event.id == event.id
        assert state == "too_early"
        assert reg.status == "registered"
        assert reg.checkin_at is None
        assert await xp_total(session, user.id) == 0


async def test_checkin_before_window_is_blocked(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21101, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21102)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now + timedelta(minutes=61))
        reg = await register_for_event(session, user.id, event.id)

        _, state = await checkin_for_event(session, user.id, event.checkin_token, now=now)

        assert state == "too_early"
        assert reg.status == "registered"


async def test_checkin_window_boundaries_are_inclusive(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21201, name="Адмін", role=UserRole.ADMIN.value)
        user_open = await create_user(session, tg_id=21202)
        user_close = await create_user(session, tg_id=21203)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now + timedelta(hours=2))
        await register_for_event(session, user_open.id, event.id)
        await register_for_event(session, user_close.id, event.id)

        opens_at = event.starts_at - timedelta(minutes=60)
        closes_at = event.starts_at + timedelta(minutes=360)
        _, open_state = await checkin_for_event(session, user_open.id, event.checkin_token, now=opens_at)
        _, close_state = await checkin_for_event(session, user_close.id, event.checkin_token, now=closes_at)

        assert open_state == "ok"
        assert close_state == "ok"
        assert (await event_checkin_window(session, event, now=opens_at))["state"] == "open"
        assert (await event_checkin_window(session, event, now=closes_at))["state"] == "open"


async def test_checkin_after_window_is_blocked(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21301, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21302)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now - timedelta(minutes=361))
        reg = await register_for_event(session, user.id, event.id)

        _, state = await checkin_for_event(session, user.id, event.checkin_token, now=now)

        assert state == "window_closed"
        assert reg.status == "registered"
        assert reg.checkin_at is None


async def test_manual_override_requires_reason_and_awards_once(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21401, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21402)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now + timedelta(days=1))
        reg = EventRegistration(event_id=event.id, user_id=user.id, status="checked_in", checkin_at=now)
        session.add(reg)
        await session.flush()

        assert await confirm_single_event_attendance(session, event, reg, admin, now=now) is None
        assert await xp_total(session, user.id) == 0

        result = await confirm_single_event_attendance(
            session, event, reg, admin, override_reason="Виправлення помилки координатора", now=now
        )
        assert result is not None
        assert reg.status == "attended"
        assert await xp_total(session, user.id) == event.xp_reward
        assert await confirm_single_event_attendance(
            session, event, reg, admin, override_reason="Повторна спроба", now=now
        ) is None
        assert await xp_total(session, user.id) == event.xp_reward


async def test_repeat_checkin_is_idempotent_and_does_not_award_xp(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21501, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21502)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now + timedelta(minutes=30))
        reg = await register_for_event(session, user.id, event.id)

        _, first = await checkin_for_event(session, user.id, event.checkin_token, now=now)
        _, second = await checkin_for_event(session, user.id, event.checkin_token, now=now + timedelta(seconds=10))
        count = await session.scalar(select(func.count(EventRegistration.id)).where(
            EventRegistration.event_id == event.id, EventRegistration.user_id == user.id
        ))

        assert first == second == "ok"
        assert count == 1
        assert reg.status == "checked_in"
        assert await xp_total(session, user.id) == 0


async def test_double_attendance_confirmation_cannot_double_xp(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21601, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21602)
        now = datetime.utcnow().replace(microsecond=0)
        event = await _event(session, admin, starts_at=now)
        reg = await register_for_event(session, user.id, event.id)
        _, state = await checkin_for_event(session, user.id, event.checkin_token, now=now)
        assert state == "ok"

        first = await confirm_single_event_attendance(session, event, reg, admin, now=now)
        second = await confirm_single_event_attendance(session, event, reg, admin, now=now)

        assert first is not None
        assert second is None
        assert await xp_total(session, user.id) == event.xp_reward


async def test_future_attendance_never_enters_monthly_attendance_kpis(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=21701, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=21702)
        now = datetime.utcnow().replace(microsecond=0)
        # Use next month so this remains a genuine future monthly report regardless
        # of the current day within this month.
        if now.month == 12:
            fy, fm = now.year + 1, 1
        else:
            fy, fm = now.year, now.month + 1
        start, end, label = resolve_report_period("month", year=fy, month=fm)
        event = await _event(session, admin, starts_at=start + timedelta(days=10, hours=12), title="Майбутня подія")
        # Simulate a legacy/bad row from an older release. v1.10.3 must not count it.
        session.add(EventRegistration(
            event_id=event.id, user_id=user.id, status="attended",
            checkin_at=now, confirmed_at=now,
        ))
        await session.flush()

        report = await build_period_report(session, start, end, label)

        assert report["summary"]["events"] == 0
        assert report["summary"]["events_planned"] == 1
        assert report["summary"]["events_upcoming"] == 1
        assert report["summary"]["visits"] == 0
        assert report["summary"]["avg_attendance"] == 0
        assert report["summary"]["unique_participants"] == 0
        assert report["summary"]["future_attendance_anomalies"] == 1
        assert report["events"][0]["timing_state"] == "upcoming"
        assert report["events"][0]["attended"] == 0


async def test_settlement_directory_normalizes_known_aliases(db):
    async with db.session_factory() as session:
        u1 = await create_user(session, tg_id=21801)
        u2 = await create_user(session, tg_id=21802)
        u3 = await create_user(session, tg_id=21803)
        u1.settlement = "Анисів"
        u2.settlement = "Анисiв"
        u3.settlement = "с.Анисів"
        await session.flush()

        changed = await ensure_settlement_directory(session)
        await session.flush()
        quality = await settlement_quality_report(session)

        assert changed == 2
        assert {u1.settlement, u2.settlement, u3.settlement} == {"Анисів"}
        assert quality["duplicate_count"] == 0
        assert quality["noncanonical_count"] == 0


def test_web_manual_override_requires_reason_and_writes_audit():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "app/web/routes/events.py").read_text(encoding="utf-8")
    template = (Path(__file__).resolve().parents[1] / "app/web/templates/event_detail.html").read_text(encoding="utf-8")

    assert 'len(reason) < 5' in source
    assert 'web_event_attendance_override' in source
    assert 'override_reason: str = Form("")' in source
    assert 'name="override_reason"' in template
    assert 'requireAttendanceOverride' in template
