"""Explicitly enabled QR-punctuality quests; all mutations share the check-in transaction."""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape as html_escape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..gamification import normalize_quest_xp
from ..model_domains import Event, Quest, QuestParticipation, User, UserStatus
from ..time_utils import clock
from .audit import log_audit
from .gamification import add_xp, evaluate_automatic_badges


def punctuality_eligible(quest: Quest, event: Event, scanned_at: datetime) -> bool:
    """The original QR scan, not attendance confirmation time, determines punctuality."""
    if (quest.quest_type != "individual" or quest.completion_mode != "qr_on_time"
            or quest.event_id != event.id or not quest.active or quest.status not in {"open", "postponed"}
            or quest.cancelled_at):
        return False
    stamp = clock.ensure_utc(scanned_at)
    event_start = clock.event_utc(event.starts_at)
    if event_start is None or stamp > event_start + timedelta(minutes=max(0, min(120, int(quest.punctuality_grace_minutes or 0)))):
        return False
    if quest.starts_at and stamp < clock.from_storage_utc(quest.starts_at):
        return False
    if quest.ends_at and stamp > clock.local_wall_to_utc(quest.ends_at):
        return False
    return True


async def award_punctuality_quests_for_scan(
    session: AsyncSession, event: Event, user_id: int, *, scanned_at: datetime,
) -> list[Quest]:
    """Auto-enroll and award once. Caller commits only with a successful QR check-in.

    The participation's unique (quest_id, user_id) constraint prevents a duplicate
    participation. PostgreSQL row locks serialize racing scans/approvals; the
    conflict-tolerant insert also handles a participant joining concurrently.
    """
    # Lock the wallet owner before writing XP; concurrent scans of different
    # quests should not overwrite one another's spendable wallet balance.
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if not user or user.status != UserStatus.ACTIVE.value:
        return []
    quests = (await session.scalars(select(Quest).where(
        Quest.event_id == event.id, Quest.completion_mode == "qr_on_time",
        Quest.quest_type == "individual", Quest.active.is_(True),
        Quest.status.in_(("open", "postponed")), Quest.cancelled_at.is_(None),
    ).order_by(Quest.id))).all()
    awarded: list[Quest] = []
    for quest in quests:
        if not punctuality_eligible(quest, event, scanned_at):
            continue
        dialect = session.get_bind().dialect.name
        values = {"quest_id": quest.id, "user_id": user.id, "status": "joined", "joined_at": clock.storage_utc(scanned_at)}
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
            await session.execute(insert(QuestParticipation).values(**values).on_conflict_do_nothing(
                index_elements=["quest_id", "user_id"]
            ))
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
            await session.execute(insert(QuestParticipation).values(**values).on_conflict_do_nothing(
                index_elements=["quest_id", "user_id"]
            ))
        participation = await session.scalar(select(QuestParticipation).where(
            QuestParticipation.quest_id == quest.id, QuestParticipation.user_id == user.id,
        ).with_for_update().execution_options(populate_existing=True))
        # A participant may decline/cancel a quest or have been returned to
        # moderation; a later scan must not silently override that decision.
        if not participation or participation.status not in {"joined", "completed"}:
            continue
        quest.xp_reward = normalize_quest_xp(quest.xp_reward, "individual")
        await add_xp(session, user, quest.xp_reward,
                     f"Автоматично виконано квест «{quest.title}»: своєчасна QR-відмітка",
                     category="quest", event_id=event.id)
        participation.status = "approved"
        participation.completed_at = clock.storage_utc(scanned_at)
        participation.approved_at = clock.storage_utc(scanned_at)
        await evaluate_automatic_badges(session, user)
        await log_audit(session, "quest_qr_on_time_awarded", actor_label="Система · QR-відмітка",
                        entity_type="quest_participation", entity_id=participation.id,
                        details=f"Подія {event.id}; квест {quest.id}; учасник {user.id}; час {clock.storage_utc(scanned_at).isoformat()}; +{quest.xp_reward} XP")
        if user.tg_id:
            from ..reliability import queue_telegram_delivery
            await queue_telegram_delivery(
                session, user.tg_id,
                f"🎯 <b>Квест «{html_escape(quest.title)}» виконано автоматично!</b>\n"
                f"Своєчасна відмітка на події «{html_escape(event.title)}».\n⚡ +{quest.xp_reward} балів досвіду.",
                source="quest_qr_on_time", recipient_user_id=user.id,
                entity_type="quest", entity_id=quest.id,
                dedupe_key=f"quest_qr_on_time:{quest.id}:{user.id}",
            )
        awarded.append(quest)
    return awarded
