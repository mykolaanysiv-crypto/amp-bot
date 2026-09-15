from .common import *  # noqa: F401,F403

async def log_audit(
    session: AsyncSession,
    action: str,
    actor: User | None = None,
    actor_label: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: str = "",
) -> AuditLog:
    row = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_label=actor_label or (actor.full_name if actor else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    session.add(row)
    await session.flush()
    return row


