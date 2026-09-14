from app.models import User, UserStatus, UserStatusChangeRequest
from app.services import ensure_user_tokens


async def test_registration_pending_to_approved_active(db):
    async with db.session_factory() as session:
        user = User(tg_id=10001, full_name="Новий Учасник", status=UserStatus.PENDING.value)
        session.add(user)
        await session.flush()
        await ensure_user_tokens(session, user)
        request = UserStatusChangeRequest(
            user_id=user.id,
            previous_status=UserStatus.PENDING.value,
            requested_status=UserStatus.ACTIVE.value,
            requested_by_label="web-admin",
        )
        session.add(request)
        await session.flush()
        user.status = UserStatus.ACTIVE.value
        request.status = "approved"
        await session.commit()

        assert user.status == UserStatus.ACTIVE.value
        assert request.status == "approved"
        assert user.public_token
        assert user.referral_code
