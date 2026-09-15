from .common import *  # noqa: F401,F403
from .audit import log_audit

async def process_expired_bans(session: AsyncSession, now: datetime | None = None) -> int:
    """Automatically reactivate users whose temporary ban has expired."""
    now = now or datetime.utcnow()
    users = (await session.scalars(
        select(User).where(
            User.status == UserStatus.BLOCKED.value,
            User.blocked_until.is_not(None),
            User.blocked_until <= now,
        )
    )).all()
    for user in users:
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
        await log_audit(session, "temporary_ban_expired", actor_label="system", entity_type="user", entity_id=user.id, details="Тимчасове блокування завершено автоматично")
    return len(users)


