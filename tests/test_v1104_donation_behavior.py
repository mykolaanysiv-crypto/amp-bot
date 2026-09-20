from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.donations import award_donation_badges
from app.model_domains import Badge, DonationTransaction, UserBadge, UserRole
from tests.conftest import create_user


async def _badge_names(session, user_id: int) -> set[str]:
    return set((await session.scalars(
        select(Badge.name).join(UserBadge, UserBadge.badge_id == Badge.id).where(UserBadge.user_id == user_id)
    )).all())


async def test_donation_badge_thresholds_and_strict_cumulative_rule(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=99101)
        session.add(DonationTransaction(provider_transaction_id="v1104-a", occurred_at=datetime.utcnow(), amount_kop=200000, currency_code=980, linked_user_id=user.id))
        await session.flush()
        await award_donation_badges(session, user.id)
        await session.commit()

        names = await _badge_names(session, user.id)
        assert {"Мій перший донат", "Мажор", "Мафіозі", "Меценат"} <= names
        # Exactly 2000 UAH is not enough because the requested cumulative rule is > 2000.
        assert "Почесний спонсор АМП" not in names

        session.add(DonationTransaction(provider_transaction_id="v1104-b", occurred_at=datetime.utcnow(), amount_kop=1, currency_code=980, linked_user_id=user.id))
        await session.flush()
        await award_donation_badges(session, user.id)
        await session.commit()
        names = await _badge_names(session, user.id)
        assert "Почесний спонсор АМП" in names


async def test_bruce_badge_is_exclusive_to_ambassador_roles(db):
    async with db.session_factory() as session:
        participant = await create_user(session, tg_id=99102)
        ambassador = await create_user(session, tg_id=99103, role=UserRole.AMBASSADOR.value)
        session.add_all([
            DonationTransaction(provider_transaction_id="v1104-c", occurred_at=datetime.utcnow(), amount_kop=500001, currency_code=980, linked_user_id=participant.id),
            DonationTransaction(provider_transaction_id="v1104-d", occurred_at=datetime.utcnow(), amount_kop=500001, currency_code=980, linked_user_id=ambassador.id),
        ])
        await session.flush()
        await award_donation_badges(session, participant.id)
        await award_donation_badges(session, ambassador.id)
        await session.commit()

        assert "Брюс Всемогутній" not in await _badge_names(session, participant.id)
        assert "Брюс Всемогутній" in await _badge_names(session, ambassador.id)
