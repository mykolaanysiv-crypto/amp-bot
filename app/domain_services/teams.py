from ..time_utils import clock
from .common import (
    AsyncSession, IntegrityError, Quest, QuestParticipation, Team, TeamMember, User, UserStatus, normalize_quest_xp, select
)
from .audit import log_audit
from .gamification import add_xp

async def seed_default_team(session: AsyncSession) -> Team:
    team = await session.scalar(select(Team).where(Team.name == "АМПасадори"))
    if not team:
        try:
            async with session.begin_nested():
                session.add(Team(name="АМПасадори", description="Основна волонтерська команда Анисівського молодіжного простору"))
                await session.flush()
        except IntegrityError:
            pass
        team = await session.scalar(select(Team).where(Team.name == "АМПасадори"))
    if not team:
        raise RuntimeError("Не вдалося створити або отримати команду АМПасадори")
    return team


async def add_active_users_to_default_team(session: AsyncSession) -> None:
    team = await seed_default_team(session)
    users = (await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value))).all()
    for user in users:
        exists = await session.scalar(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id))
        if exists:
            continue
        try:
            async with session.begin_nested():
                session.add(TeamMember(team_id=team.id, user_id=user.id))
                await session.flush()
        except IntegrityError:
            # Another worker attached the same user to the default team.
            pass


async def complete_team_quest(session: AsyncSession, quest: Quest, admin_user: User | None = None) -> int:
    if quest.quest_type != "team" or quest.completed:
        return 0
    if quest.progress_value < quest.target_value:
        return 0

    # v1.5: a team quest has an explicit participant list. Reward only people
    # who actually joined the quest. For legacy team quests without joins, fall
    # back to the default team so older data keeps working.
    parts = (await session.scalars(
        select(QuestParticipation).where(
            QuestParticipation.quest_id == quest.id,
            QuestParticipation.status.in_(["joined", "completed"]),
        )
    )).all()
    user_ids = [p.user_id for p in parts]
    if not user_ids and quest.team_id:
        members = (await session.scalars(select(TeamMember).where(TeamMember.team_id == quest.team_id))).all()
        user_ids = [m.user_id for m in members]

    quest.xp_reward = normalize_quest_xp(quest.xp_reward, "team")
    count = 0
    for user_id in dict.fromkeys(user_ids):
        user = await session.get(User, user_id)
        if not user or user.status != UserStatus.ACTIVE.value:
            continue
        await add_xp(
            session, user, quest.xp_reward, f"Командний квест «{quest.title}»",
            category="team_quest", created_by=admin_user.id if admin_user else None,
        )
        part = next((p for p in parts if p.user_id == user_id), None)
        if part:
            part.status = "approved"
            if not part.completed_at:
                part.completed_at = clock.storage_utc()
            part.approved_at = clock.storage_utc()
        count += 1
    quest.completed = True
    quest.active = False
    await log_audit(session, "team_quest_completed", admin_user, entity_type="quest", entity_id=quest.id, details=f"Нагороджено: {count}")
    return count


