from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.model_domains import EventRegistration, UserRole
from app.domain_services import (
    checkin_for_event,
    confirm_single_event_attendance,
    create_event,
    force_event_registration_status,
    process_event_operations,
    register_for_event,
    xp_total,
)
from app.time_utils import clock
from tests.conftest import create_user


async def test_preregistered_attendee_gets_base_plus_bonus(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=1170401, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=1170402, name="Учасник")
        event = await create_event(
            session,
            "Подія з бонусом",
            "",
            clock.local_wall() + timedelta(minutes=30),
            "АМП",
            10,
            1.5,
            admin.id,
            preregistration_bonus_xp=5,
            no_show_penalty_xp=5,
        )
        reg = await register_for_event(session, user.id, event.id)
        checked_event, state = await checkin_for_event(session, user.id, event.checkin_token)
        assert state == "ok" and checked_event and checked_event.id == event.id
        await session.flush()

        result = await confirm_single_event_attendance(session, event, reg, admin)
        assert result is not None
        assert reg.status == "attended"
        assert reg.attendance_xp_awarded == 10
        assert reg.preregistration_bonus_xp_awarded == 5
        assert reg.no_show_penalty_xp_applied == 0
        assert user.volunteer_hours == 1.5
        assert await xp_total(session, user.id) == 15


async def test_door_scanner_registration_does_not_get_preregistration_bonus(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=1170411, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=1170412, name="Гість")
        event = await create_event(
            session,
            "Вхід без реєстрації",
            "",
            clock.local_wall() + timedelta(minutes=20),
            "АМП",
            10,
            0,
            admin.id,
            preregistration_bonus_xp=5,
            no_show_penalty_xp=5,
        )
        checked_event, state = await checkin_for_event(session, user.id, event.checkin_token)
        assert state == "ok" and checked_event
        reg = await session.scalar(
            select(EventRegistration).where(
                EventRegistration.event_id == event.id,
                EventRegistration.user_id == user.id,
            )
        )
        assert reg is not None
        assert reg.registration_source == "scanner"
        result = await confirm_single_event_attendance(session, event, reg, admin)
        assert result is not None
        assert reg.attendance_xp_awarded == 10
        assert reg.preregistration_bonus_xp_awarded == 0
        assert await xp_total(session, user.id) == 10


async def test_completed_no_show_applies_penalty_exactly_once(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=1170421, name="Адмін", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=1170422, name="Неявка")
        event = await create_event(
            session,
            "Минувша подія",
            "",
            clock.local_wall() - timedelta(hours=2),
            "АМП",
            10,
            0,
            admin.id,
            preregistration_bonus_xp=5,
            no_show_penalty_xp=5,
        )
        event.status = "completed"
        reg = await register_for_event(session, user.id, event.id)
        await session.flush()

        changed = await process_event_operations(session, event_id=event.id)
        assert changed["no_show"] == 1
        assert changed["no_show_penalty"] == 1
        assert reg.status == "no_show"
        assert reg.no_show_penalty_xp_applied == 5
        assert await xp_total(session, user.id) == -5

        changed_again = await process_event_operations(session, event_id=event.id)
        assert changed_again["no_show"] == 0
        assert changed_again["no_show_penalty"] == 0
        assert await xp_total(session, user.id) == -5


async def test_superadmin_status_correction_reconciles_penalty_bonus_and_hours(db):
    async with db.session_factory() as session:
        superadmin = await create_user(session, tg_id=1170431, name="Суперадмін", role=UserRole.SUPERADMIN.value)
        user = await create_user(session, tg_id=1170432, name="Учасник")
        event_start = clock.local_wall() - timedelta(hours=2)
        event = await create_event(
            session,
            "Коригування статусу",
            "",
            event_start,
            "АМП",
            10,
            2,
            superadmin.id,
            preregistration_bonus_xp=5,
            no_show_penalty_xp=5,
        )
        event.status = "completed"
        reg = EventRegistration(
            event_id=event.id,
            user_id=user.id,
            status="registered",
            registration_source="participant",
            registered_at=clock.storage_utc(clock.event_utc(event_start) - timedelta(hours=1)),
        )
        session.add(reg)
        await session.flush()

        await process_event_operations(session, event_id=event.id)
        assert reg.status == "no_show"
        assert await xp_total(session, user.id) == -5

        change = await force_event_registration_status(session, event, reg, "attended", superadmin)
        assert change["previous_status"] == "no_show"
        assert reg.status == "attended"
        assert reg.no_show_penalty_xp_applied == 0
        assert reg.attendance_xp_awarded == 10
        assert reg.preregistration_bonus_xp_awarded == 5
        assert user.volunteer_hours == 2
        assert await xp_total(session, user.id) == 15

        # Repeating the same correction is idempotent: no duplicate XP/hours.
        again = await force_event_registration_status(session, event, reg, "attended", superadmin)
        assert again["base_delta"] == 0
        assert again["bonus_delta"] == 0
        assert again["penalty_delta"] == 0
        assert again["hours_delta"] == 0
        assert await xp_total(session, user.id) == 15
        assert user.volunteer_hours == 2
