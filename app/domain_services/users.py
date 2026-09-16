from ..time_utils import clock
from .common import (
    AsyncSession, BanRecord, User, UserStatus, date, select, token_urlsafe
)

def age_on(birth_date: date, today: date | None = None) -> int:
    today = today or clock.today_local()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


async def get_user_by_tg(session: AsyncSession, tg_id: int) -> User | None:
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    # Restore access immediately when a temporary ban has expired, even before
    # the hourly maintenance job runs. This keeps Telegram behaviour intuitive.
    if user and user.status == UserStatus.BLOCKED.value and user.blocked_until and user.blocked_until <= clock.storage_utc():
        now = clock.storage_utc()
        active_ban = await session.scalar(
            select(BanRecord).where(
                BanRecord.user_id == user.id,
                BanRecord.lifted_at.is_(None),
            ).order_by(BanRecord.started_at.desc())
        )
        if active_ban:
            active_ban.lifted_at = now
            active_ban.lift_reason = "Строк блокування завершився автоматично"
            active_ban.updated_at = now
        user.status = UserStatus.ACTIVE.value
        user.blocked_until = None
        user.block_reason = None
        await session.commit()
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def ensure_user_tokens(session: AsyncSession, user: User) -> None:
    if not user.public_token:
        user.public_token = token_urlsafe(18)
    if not user.referral_code:
        # compact human-shareable code; uniqueness is additionally enforced by DB index
        user.referral_code = f"AMP{user.id:04d}{token_urlsafe(4).replace('-', '').replace('_', '')[:5]}".upper()


