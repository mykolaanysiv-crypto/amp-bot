from ..time_utils import clock
from .common import (
    AsyncSession, Referral, Settings, User, UserStatus, datetime, func, get_runtime_int, select, timedelta
)
from .audit import log_audit
from .gamification import add_xp, evaluate_automatic_badges

async def create_referral_for_user(session: AsyncSession, new_user: User, referral_code: str | None) -> Referral | None:
    if not referral_code:
        return None
    inviter = await session.scalar(select(User).where(User.referral_code == referral_code))
    if not inviter or inviter.id == new_user.id:
        return None
    new_user.referred_by_user_id = inviter.id
    referral = Referral(inviter_user_id=inviter.id, invited_user_id=new_user.id, status="pending")
    session.add(referral)
    await session.flush()
    return referral


def referral_quarter_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return [quarter_start, next_quarter_start) for the supplied UTC datetime."""
    now = now or clock.storage_utc()
    start_month = ((now.month - 1) // 3) * 3 + 1
    start = datetime(now.year, start_month, 1)
    if start_month == 10:
        end = datetime(now.year + 1, 1, 1)
    else:
        end = datetime(now.year, start_month + 3, 1)
    return start, end


async def referral_quarter_summary(
    session: AsyncSession, inviter_user_id: int, now: datetime | None = None
) -> tuple[int, int, datetime, datetime]:
    """Return rewarded referrals this quarter and XP for the next successful one."""
    start, end = referral_quarter_bounds(now)
    count = int(await session.scalar(
        select(func.count(Referral.id)).where(
            Referral.inviter_user_id == inviter_user_id,
            Referral.status == "rewarded",
            Referral.rewarded_at.is_not(None),
            Referral.rewarded_at >= start,
            Referral.rewarded_at < end,
        )
    ) or 0)
    base_reward = await get_runtime_int(session, "xp.referral_max")
    reward = max(1, int(base_reward) + 1 - max(1, count + 1))
    return count, reward, start, end


async def reward_referral_if_ready(
    session: AsyncSession, invited_user: User, settings: Settings, created_by: int | None = None
) -> tuple[User, int] | None:
    """Reward a successful referral using the quarterly diminishing schedule.

    1st referral in a calendar quarter = 10 XP, 2nd = 9 ... 10th = 1,
    and every subsequent successful referral in that quarter = 1 XP.
    The counter resets automatically on Jan 1, Apr 1, Jul 1 and Oct 1.
    """
    referral = await session.scalar(select(Referral).where(Referral.invited_user_id == invited_user.id))
    if not referral or referral.status != "pending" or invited_user.status != UserStatus.ACTIVE.value:
        return None
    inviter = await session.get(User, referral.inviter_user_id)
    if not inviter:
        return None
    count, reward, _, _ = await referral_quarter_summary(session, inviter.id)
    referral.xp_reward = reward
    referral.status = "rewarded"
    referral.rewarded_at = clock.storage_utc()
    await add_xp(
        session,
        inviter,
        reward,
        f"Запрошено нового активного учасника: {invited_user.full_name} (№{count + 1} у кварталі)",
        category="referral",
        created_by=created_by,
    )
    await evaluate_automatic_badges(session, inviter)
    return inviter, reward


async def revoke_referral_reward_if_inactive(
    session: AsyncSession,
    invited_user: User,
    *,
    reason: str = "Учасник став неактивним",
    now: datetime | None = None,
    window_days: int = 30,
) -> tuple[User, int, int] | None:
    """Claw back referral XP when the invited account becomes inactive within 30 days.

    The operation is idempotent: only referrals in ``rewarded`` state can be revoked.
    Returns (inviter, xp_removed, days_after_reward) when a clawback was applied.
    """
    now = now or clock.storage_utc()
    referral = await session.scalar(select(Referral).where(Referral.invited_user_id == invited_user.id))
    if not referral or referral.status != "rewarded" or not referral.rewarded_at or int(referral.xp_reward or 0) <= 0:
        return None
    elapsed = now - referral.rewarded_at
    if elapsed.total_seconds() < 0 or elapsed > timedelta(days=max(1, int(window_days))):
        return None
    inviter = await session.get(User, referral.inviter_user_id)
    if not inviter:
        return None
    amount = int(referral.xp_reward or 0)
    days_after = max(0, elapsed.days)
    await add_xp(
        session, inviter, -amount,
        f"Повернення бонусу за запрошення: {invited_user.full_name} став(ла) неактивним(ою) протягом {window_days} днів",
        category="referral_reversal",
    )
    referral.status = "revoked"
    referral.revoked_at = now
    referral.revoke_reason = (reason or "Учасник став неактивним")[:500]
    referral.clawback_xp = amount
    await log_audit(
        session, "referral_reward_revoked", actor_label="system", entity_type="referral", entity_id=referral.id,
        details=f"invited_user={invited_user.id}; inviter={inviter.id}; xp=-{amount}; days={days_after}; reason={referral.revoke_reason}",
    )
    return inviter, amount, days_after


