from .common import *  # noqa: F401,F403
from .gamification import ensure_default_season, seed_activity_types, seed_badges, seed_default_space_rewards, seed_streak_restore_reward
from .teams import add_active_users_to_default_team
from .users import ensure_user_tokens, get_user_by_tg


# Serialize startup seeding within a single process. In v1.12.0 this lock
# was accidentally dropped while splitting services.py into domain modules.
# Cross-process safety is still provided by idempotent DB operations/constraints.
_bootstrap_lock = asyncio.Lock()

async def ensure_superadmins(session: AsyncSession, ids: set[int]) -> None:
    """Ensure configured Telegram IDs exist and have superadmin rights.

    The function is idempotent. The nested transaction also makes the insert
    tolerant of a concurrent bootstrap in another process (for example bot +
    web containers starting against the same PostgreSQL database).
    """
    for tg_id in ids:
        user = await get_user_by_tg(session, tg_id)
        if not user:
            try:
                async with session.begin_nested():
                    candidate = User(
                        tg_id=tg_id,
                        username=None,
                        full_name=f"Суперадміністратор {tg_id}",
                        role=UserRole.SUPERADMIN.value,
                        status=UserStatus.ACTIVE.value,
                    )
                    session.add(candidate)
                    await session.flush()
            except IntegrityError:
                # Another startup worker inserted the same tg_id first.
                pass
            user = await get_user_by_tg(session, tg_id)

        if user:
            user.role = UserRole.SUPERADMIN.value
            user.status = UserStatus.ACTIVE.value
            await ensure_user_tokens(session, user)


async def ensure_web_staff_accounts(session: AsyncSession, settings: Settings) -> None:
    """Migrate legacy env credentials into hashed DB accounts once.

    Existing DB accounts are never overwritten from environment variables. This
    makes WEB_ADMIN_PASSWORD / WEB_STAFF_ACCOUNTS_JSON bootstrap-only and allows
    operators to remove them from Heroku after the first successful v1.7.3 boot.
    """
    super_username = (settings.web_admin_username or "admin").strip()
    if super_username:
        row = await session.scalar(select(WebStaffAccount).where(WebStaffAccount.username == super_username))
        if not row and settings.web_admin_password:
            tg_id = min(settings.superadmin_ids) if settings.superadmin_ids else None
            session.add(WebStaffAccount(
                username=super_username,
                password_hash=hash_password(settings.web_admin_password),
                display_name="Суперадміністратор",
                role="superadmin",
                active=True,
                must_change_password=True,
                two_factor_enabled=True,
                two_factor_tg_id=tg_id,
                password_changed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ))

    for username, cfg in (settings.web_staff_accounts or {}).items():
        username = (username or "").strip()
        if not username:
            continue
        exists = await session.scalar(select(WebStaffAccount).where(WebStaffAccount.username == username))
        if exists:
            continue
        password = str(cfg.get("password") or "")
        if not password:
            continue
        session.add(WebStaffAccount(
            username=username,
            password_hash=hash_password(password),
            display_name=str(cfg.get("display_name") or username),
            role="admin",
            active=True,
            must_change_password=True,
            two_factor_enabled=False,
            password_changed_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))


async def ensure_event_share_tokens(session: AsyncSession) -> int:
    """Backfill safe public-share tokens for legacy events without exposing check-in tokens."""
    rows = (await session.scalars(select(Event).where(Event.share_token.is_(None)))).all()
    for event in rows:
        event.share_token = token_urlsafe(18)
    if rows:
        await session.flush()
    return len(rows)


async def bootstrap_defaults(db, settings: Settings) -> None:
    """Create/update startup defaults exactly once per process.

    Both the bot and FastAPI app call this helper. The lock ensures the second
    caller waits until the first transaction has committed, so it sees the
    already-created superadmin, season, badges and default team.
    """
    async with _bootstrap_lock:
        async with db.session_factory() as session:
            from ..settlements import ensure_settlement_directory
            from ..donations import ensure_donation_badges
            await ensure_runtime_defaults(session)
            await ensure_settlement_directory(session)
            await ensure_superadmins(session, settings.superadmin_ids)
            await ensure_web_staff_accounts(session, settings)
            await ensure_default_season(session, settings)
            await seed_badges(session)
            await ensure_donation_badges(session)
            await seed_activity_types(session)
            await seed_streak_restore_reward(session)
            await seed_default_space_rewards(session)
            await ensure_event_share_tokens(session)
            await add_active_users_to_default_team(session)
            await session.commit()


