from datetime import datetime

from app.models import BroadcastCampaign, BroadcastRecipient
from tests.conftest import create_user


async def test_broadcast_recipient_retry_state_is_persisted(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=16001)
        campaign = BroadcastCampaign(message_text="Привіт", recipient_count=1, status="queued")
        session.add(campaign); await session.flush()
        recipient = BroadcastRecipient(
            campaign_id=campaign.id, user_id=user.id, recipient_name=user.full_name,
            recipient_tg_id=user.tg_id, status="retry", attempt_count=1,
            next_retry_at=datetime.utcnow(), error_text="temporary",
        )
        session.add(recipient); await session.commit()
        assert recipient.status == "retry"
        assert recipient.attempt_count == 1
        assert recipient.next_retry_at is not None
