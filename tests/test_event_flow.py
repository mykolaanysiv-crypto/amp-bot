from datetime import datetime, timedelta

from app.model_domains import UserRole
from app.domain_services import checkin_for_event, confirm_single_event_attendance, create_event, register_for_event, xp_total
from tests.conftest import create_user


async def test_event_register_checkin_confirm_awards_xp_once(db):
    async with db.session_factory() as session:
        admin = await create_user(session, tg_id=11001, name="Адмін АМП", role=UserRole.ADMIN.value)
        user = await create_user(session, tg_id=11002)
        event = await create_event(session, "Тестова подія", "", datetime.utcnow() + timedelta(minutes=30), "АМП", 20, 1.5, admin.id)
        reg = await register_for_event(session, user.id, event.id)
        assert reg.status == "registered"
        checked_event, state = await checkin_for_event(session, user.id, event.checkin_token)
        assert state == "ok" and checked_event.id == event.id
        await session.flush()
        result = await confirm_single_event_attendance(session, event, reg, admin)
        assert result is not None
        assert reg.status == "attended"
        assert reg.attendance_signature is not None
        assert len(reg.attendance_signature) == 64
        assert reg.attendance_signature_version == "sha256-v1"
        assert reg.attendance_signature_created_at is not None
        assert reg.attendance_confirmed_by_user_id == admin.id
        signature = reg.attendance_signature
        assert user.volunteer_hours == 1.5
        assert await xp_total(session, user.id) == event.xp_reward
        assert await confirm_single_event_attendance(session, event, reg, admin) is None
        assert reg.attendance_signature == signature
        await session.commit()
