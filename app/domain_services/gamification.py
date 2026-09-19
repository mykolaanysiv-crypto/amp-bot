from ..time_utils import clock
from ..badge_seeds import badge_seed_is_deleted
from html import escape as html_escape
from .common import (
    ActivityApplication, ActivityType, AsyncSession, Badge, CLAIMABLE_ACTIVITY_CATALOG, EventRegistration, Idea, IntegrityError, ParticipationStreak, QuestParticipation, Referral, Reward, Season, Settings, SurveyResponse, User, UserBadge, UserStatus, VolunteerTaskParticipation, XPTransaction, date, datetime, func, get_level, get_runtime_int, mark_first_activity, participant_first_name, select, timedelta
)

async def current_season(session: AsyncSession) -> Season | None:
    return await session.scalar(select(Season).where(Season.active == True).order_by(Season.starts_at.desc()))  # noqa: E712


async def ensure_default_season(session: AsyncSession, settings: Settings) -> Season:
    """Ensure an initial season without re-activating archived history.

    v1.9.2 makes seasons historical objects. If an administrator has already
    created another active season, startup must respect it instead of forcing
    the config-named season back to active. Likewise, a finalized/expired
    configured season is never resurrected after restart.
    """
    active = await current_season(session)
    if active:
        season = active
    else:
        season = await session.scalar(select(Season).where(Season.name == settings.season_name))
        if not season:
            try:
                async with session.begin_nested():
                    candidate = Season(
                        name=settings.season_name,
                        starts_at=settings.season_start,
                        ends_at=settings.season_end,
                        active=settings.season_end >= clock.today_local(),
                        archived=settings.season_end < clock.today_local(),
                    )
                    session.add(candidate)
                    await session.flush()
            except IntegrityError:
                pass
            season = await session.scalar(select(Season).where(Season.name == settings.season_name))
            if not season:
                raise RuntimeError(f"Не вдалося створити або отримати сезон: {settings.season_name}")
        # Only sync dates for a non-finalized config season. Historical snapshots
        # must remain stable after archival.
        if not season.finalized_at:
            season.starts_at = settings.season_start
            season.ends_at = settings.season_end
            if settings.season_end >= clock.today_local():
                season.active = True
                season.archived = False

    # Backfill legacy XP into whichever season is currently selected. Season
    # dates are local-calendar boundaries while XP timestamps are stored as
    # naive UTC in the legacy schema, so convert the full local interval once.
    start_local = datetime.combine(season.starts_at, datetime.min.time())
    end_local = datetime.combine(season.ends_at + timedelta(days=1), datetime.min.time())
    start_dt, end_dt = clock.local_period_to_storage_utc(start_local, end_local)
    legacy = (await session.scalars(select(XPTransaction).where(
        XPTransaction.season_id.is_(None),
        XPTransaction.created_at >= start_dt,
        XPTransaction.created_at < end_dt,
    ))).all()
    for tx in legacy:
        tx.season_id = season.id
    return season


async def xp_total(session: AsyncSession, user_id: int) -> int:
    value = await session.scalar(
        select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(XPTransaction.user_id == user_id)
    )
    return int(value or 0)


async def season_xp(session: AsyncSession, user_id: int, season_id: int | None = None) -> int:
    if season_id is None:
        season = await current_season(session)
        if not season:
            return 0
        season_id = season.id
    value = await session.scalar(
        select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(
            XPTransaction.user_id == user_id,
            XPTransaction.season_id == season_id,
        )
    )
    return int(value or 0)


async def add_xp(
    session: AsyncSession,
    user: User,
    amount: int,
    description: str,
    category: str = "other",
    created_by: int | None = None,
    event_id: int | None = None,
) -> tuple[int, str, bool]:
    before = await xp_total(session, user.id)
    before_level = get_level(before)[0]
    season = await current_season(session)
    tx = XPTransaction(
        user_id=user.id,
        amount=amount,
        description=description,
        category=category,
        created_by=created_by,
        event_id=event_id,
        season_id=season.id if season else None,
    )
    session.add(tx)
    # Spendable wallet follows earned/corrected XP, but reward redemption does not
    # change lifetime XP or level.
    user.wallet_xp = max(0, int(user.wallet_xp or 0) + amount)
    await session.flush()
    if amount >= 0 and category in {"event", "quest", "task", "team_task", "activity", "survey", "team_quest", "idea_approved"}:
        await mark_first_activity(session, user.id, tx.created_at or clock.storage_utc())
    after = before + amount
    after_level = get_level(after)[0]
    await evaluate_automatic_badges(session, user)
    return after, after_level, before_level != after_level


async def process_birthdays(session: AsyncSession, today: date) -> list[tuple[int, str, int]]:
    """Award the annual birthday bonus exactly once per calendar year.

    Returns tuples: (telegram_id, first_name, xp_awarded). Only active users with
    a birth date are eligible. The persisted birthday_reward_year makes the job
    safe across restarts and repeated scheduler runs.
    """
    birthday_xp = await get_runtime_int(session, "xp.birthday")
    users = (await session.scalars(
        select(User).where(
            User.status == UserStatus.ACTIVE.value,
            User.birth_date.is_not(None),
        )
    )).all()
    rewarded: list[tuple[int, str, int]] = []
    for user in users:
        if not user.birth_date:
            continue
        if (user.birth_date.month, user.birth_date.day) != (today.month, today.day):
            continue
        if user.birthday_reward_year == today.year:
            continue
        await add_xp(
            session,
            user,
            birthday_xp,
            "Подарунок АМП до дня народження 🎂",
            category="birthday",
        )
        user.birthday_reward_year = today.year
        first_name = participant_first_name(user)
        rewarded.append((user.tg_id, first_name, birthday_xp))
    return rewarded


async def seed_activity_types(session: AsyncSession) -> None:
    """Seed missing balanced activity types without overwriting admin edits."""
    for order, item in enumerate(CLAIMABLE_ACTIVITY_CATALOG, start=10):
        row = await session.scalar(select(ActivityType).where(ActivityType.code == item["code"]))
        if row:
            continue
        try:
            async with session.begin_nested():
                session.add(ActivityType(
                    code=item["code"], title=item["title"], category=item["category"],
                    description=item["description"], instructions=item["instructions"],
                    xp_reward=int(item["xp"]), hours_reward=float(item["hours"]),
                    active=True, sort_order=order,
                ))
                await session.flush()
        except IntegrityError:
            pass


async def complete_activity_application(
    session: AsyncSession, application: ActivityApplication, admin_user: User | None = None
) -> tuple[User, int, str, bool] | None:
    """Complete an approved/submitted application and award its snapshotted XP exactly once."""
    if application.status == "activity_completed":
        return None
    if application.status not in {"activity_approved", "activity_submitted"}:
        return None
    user = await session.get(User, application.user_id)
    activity = await session.get(ActivityType, application.activity_type_id)
    if not user or not activity:
        return None
    result = await add_xp(
        session, user, int(application.xp_reward or activity.xp_reward),
        f"Активність «{activity.title}»", category="activity",
        created_by=admin_user.id if admin_user else None,
    )
    user.volunteer_hours += float(application.hours_reward or activity.hours_reward or 0)
    application.status = "activity_completed"
    application.completed_at = clock.storage_utc()
    application.completed_by = admin_user.id if admin_user else None
    await evaluate_automatic_badges(session, user)
    return (user, *result)


async def seed_badges(session: AsyncSession) -> None:
    defaults = [
        ("core:xp_transactions:1", "Перший крок", "🚀", "Перша підтверджена активність", "xp_transactions", 1),
        ("core:xp_transactions:10", "Прокачаний", "🎓", "10 підтверджених активностей", "xp_transactions", 10),
        ("core:volunteer_hours:50", "Серце команди", "❤️", "50 волонтерських годин", "volunteer_hours", 50),
        ("core:volunteer_hours:100", "100 годин для АМП", "⏱", "100 волонтерських годин", "volunteer_hours", 100),
        ("core:referrals:3", "Магніт", "👥", "3 успішно залучені нові учасники", "referrals", 3),
        ("core:quests:5", "Квестер", "🎯", "5 підтверджених квестів", "quests", 5),
        ("core:xp_total:300", "АМПасадор", "🔥", "Досягнення 300 XP", "xp_total", 300),
        ("core:xp_total:800", "Лідер АМП", "🛰️", "Досягнення 800 XP", "xp_total", 800),
        ("core:xp_total:1200", "Легенда АМП", "🏆", "Досягнення 1200 XP", "xp_total", 1200),
    ]
    for seed_key, name, icon, desc, criteria_type, criteria_value in defaults:
        # Deleted built-in badges stay deleted across deploy/restart.
        if await badge_seed_is_deleted(session, seed_key):
            continue
        # Match built-in automatic badges by their stable business rule first,
        # then by legacy name. This lets admins rename/rewrite the visible badge
        # without bootstrap recreating a duplicate on the next deploy.
        badge = await session.scalar(select(Badge).where(
            Badge.criteria_type == criteria_type,
            Badge.criteria_value == criteria_value,
            Badge.automatic == True,  # noqa: E712
            Badge.badge_type == "general",
        ))
        if not badge:
            badge = await session.scalar(select(Badge).where(Badge.name == name))
        if not badge:
            try:
                async with session.begin_nested():
                    session.add(Badge(
                        name=name,
                        icon=icon,
                        description=desc,
                        criteria_type=criteria_type,
                        criteria_value=criteria_value,
                        automatic=True,
                        seed_key=seed_key,
                    ))
                    await session.flush()
            except IntegrityError:
                pass
            badge = await session.scalar(select(Badge).where(Badge.seed_key == seed_key))
            if not badge:
                badge = await session.scalar(select(Badge).where(
                    Badge.criteria_type == criteria_type,
                    Badge.criteria_value == criteria_value,
                    Badge.automatic == True,  # noqa: E712
                    Badge.badge_type == "general",
                ))
        if badge and not badge.seed_key:
            badge.seed_key = seed_key
        # Existing system badges are intentionally not overwritten here.
        # Their visible presentation and enabled state remain administrator-editable.

    # Manual / thematic badges remain available to admins, but can now also be
    # permanently deleted without bootstrap recreating them.
    manual = [
        ("manual:clean-start", "Чистий старт", "🧹", "Участь у толоках та благоустрої"),
        ("manual:amp-voice", "Голос АМП", "🎤", "Проведення власної активності"),
        ("manual:content-maker", "Контент-мейкер", "📸", "Внесок у комунікації та медіа"),
        ("manual:networker", "Нетворкер", "🤝", "Залучення партнерів"),
        ("manual:idea-maker", "Ідейник", "💡", "Реалізовані ідеї"),
        ("manual:mentor", "Ментор", "🧑‍🏫", "Допомога новим учасникам"),
        ("manual:change-maker", "Запускаю зміни", "🚀", "Реалізація власного мініпроєкту"),
    ]
    for seed_key, name, icon, desc in manual:
        if await badge_seed_is_deleted(session, seed_key):
            continue
        badge = await session.scalar(select(Badge).where(Badge.seed_key == seed_key))
        if not badge:
            badge = await session.scalar(select(Badge).where(Badge.name == name))
        if not badge:
            try:
                async with session.begin_nested():
                    session.add(Badge(name=name, icon=icon, description=desc, automatic=False, seed_key=seed_key))
                    await session.flush()
            except IntegrityError:
                pass
            badge = await session.scalar(select(Badge).where(Badge.seed_key == seed_key))
            if not badge:
                badge = await session.scalar(select(Badge).where(Badge.name == name))
        if badge and not badge.seed_key:
            badge.seed_key = seed_key


async def _metric_value(session: AsyncSession, user: User, criteria_type: str) -> int:
    if criteria_type == "xp_total":
        return await xp_total(session, user.id)
    if criteria_type == "volunteer_hours":
        return int(user.volunteer_hours or 0)
    if criteria_type == "xp_transactions":
        return int(await session.scalar(select(func.count(XPTransaction.id)).where(XPTransaction.user_id == user.id)) or 0)
    if criteria_type == "referrals":
        return int(await session.scalar(select(func.count(Referral.id)).where(Referral.inviter_user_id == user.id, Referral.status == "rewarded")) or 0)
    if criteria_type == "quests":
        return int(await session.scalar(select(func.count(QuestParticipation.id)).where(QuestParticipation.user_id == user.id, QuestParticipation.status == "approved")) or 0)
    if criteria_type == "events":
        return int(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.user_id == user.id, EventRegistration.status == "attended")) or 0)
    if criteria_type == "activities":
        return int(await session.scalar(select(func.count(ActivityApplication.id)).where(ActivityApplication.user_id == user.id, ActivityApplication.status == "activity_completed")) or 0)
    if criteria_type == "ideas":
        return int(await session.scalar(select(func.count(Idea.id)).where(Idea.user_id == user.id, Idea.status == "implemented")) or 0)
    if criteria_type == "tasks":
        return int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.user_id == user.id, VolunteerTaskParticipation.status == "approved")) or 0)
    if criteria_type == "surveys":
        return int(await session.scalar(select(func.count(SurveyResponse.id)).where(SurveyResponse.user_id == user.id)) or 0)
    if criteria_type in {"weekly_streak", "event_streak"}:
        streak = await session.scalar(select(ParticipationStreak).where(ParticipationStreak.user_id == user.id))
        return int(getattr(streak, criteria_type, 0) or 0) if streak else 0
    return 0


async def evaluate_automatic_badges(session: AsyncSession, user: User) -> list[Badge]:
    badges = (await session.scalars(select(Badge).where(Badge.active == True, Badge.automatic == True))).all()  # noqa: E712
    awarded: list[Badge] = []
    for badge in badges:
        if badge.badge_type == "ambassador" and user.role not in {"ambassador","coordinator","admin","superadmin"}:
            continue
        if not badge.criteria_type or badge.criteria_value is None:
            continue
        exists = await session.scalar(select(UserBadge).where(UserBadge.user_id == user.id, UserBadge.badge_id == badge.id))
        if exists:
            continue
        if badge.criteria_type in {"donation_first", "donation_single", "donation_total_over"}:
            # Donation badges have slightly different semantics from ordinary >= metrics:
            # first/single use the largest qualifying donation, while cumulative badges
            # are intentionally strict "more than" thresholds.
            from ..donations import donation_totals_for_user
            donation_total, donation_largest, donation_count = await donation_totals_for_user(session, user.id)
            if badge.criteria_type in {"donation_first", "donation_single"}:
                qualifies = donation_count > 0 and donation_largest >= int(badge.criteria_value)
            else:
                qualifies = donation_total > int(badge.criteria_value)
        else:
            value = await _metric_value(session, user, badge.criteria_type)
            qualifies = value >= badge.criteria_value
        if qualifies:
            session.add(UserBadge(user_id=user.id, badge_id=badge.id, awarded_by=None))
            await session.flush()
            # Lazy import keeps the pure gamification model/service importable in
            # lightweight analytics/tests while production still uses the canonical
            # Notification Center outbox.
            from ..reliability import queue_notification
            await queue_notification(
                session,
                user.tg_id,
                (
                    "🎉 <b>Вітаємо! Ви отримали новий бейдж</b>\n\n"
                    f"{badge.icon} <b>{html_escape(badge.name)}</b>\n"
                    f"📌 За що: {html_escape(badge.description or 'за активність у просторі АМП')}"
                ),
                source="badge",
                notification_type="badge",
                title="Новий бейдж",
                recipient_user_id=user.id,
                entity_type="badge",
                entity_id=badge.id,
                dedupe_key=f"automatic_badge:{user.id}:{badge.id}",
                button_text="🏅 Переглянути бейджі",
                callback_data="ux:mine:badges",
            )
            awarded.append(badge)
    return awarded


async def seed_streak_restore_reward(session: AsyncSession) -> None:
    existing = await session.scalar(select(Reward).where(Reward.reward_type == "streak_restore"))
    cost = await get_runtime_int(session, "xp.streak_restore_cost")
    if existing:
        existing.min_xp = cost
        return
    session.add(Reward(
        title="Повернути суперсерію",
        description="Відновлює останню втрачену суперсерію відвідування подій. Працює лише якщо є серія, доступна для відновлення.",
        min_xp=cost,
        stock=None,
        active=True,
        reward_type="streak_restore",
    ))


DEFAULT_SPACE_REWARDS = (
    ("1 год оренди кімнати в молодіжному просторі", "Оренда окремої кімнати АМП на 1 годину за попереднім погодженням з командою простору.", 15),
    ("1 год оренди всього молодіжного простору", "Оренда всього молодіжного простору на 1 годину за попереднім погодженням.", 50),
    ("4 год оренди молодіжного центру", "Оренда молодіжного центру на 4 години за попереднім погодженням.", 150),
    ("Оренда проєктора та екрану", "Оренда проєктора та екрану за попереднім погодженням і правилами користування обладнанням.", 45),
    ("Настільні ігри додому на 7 днів", "Можна взяти доступний набір настільних ігор додому на строк до 7 днів.", 100),
    ("Нова гра на PlayStation рівня AA або старше 10 років", "Запит на придбання нової гри рівня AA або гри, старшої за 10 років. Остаточний вибір погоджує команда АМП.", 50),
    ("Нова гра на PlayStation рівня AAA", "Запит на придбання нової гри рівня AAA. Остаточний вибір погоджує команда АМП.", 75),
    ("Гра на PlayStation — ексклюзив або новинка до 1 року", "Запит на придбання ексклюзиву або новинки до 1 року. Остаточний вибір погоджує команда АМП.", 100),
    ("1 година гри на приставці", "1 година гри на приставці в молодіжному просторі за правилами АМП.", 5),
)


async def seed_default_space_rewards(session: AsyncSession) -> None:
    """Add the v1.7.4.1 default reward catalog without overwriting admin edits."""
    for title, description, cost in DEFAULT_SPACE_REWARDS:
        existing = await session.scalar(select(Reward).where(Reward.title == title))
        if existing:
            continue
        session.add(Reward(title=title, description=description, min_xp=cost, stock=None, active=True, reward_type="service"))


