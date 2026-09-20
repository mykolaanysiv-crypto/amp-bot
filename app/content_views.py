from __future__ import annotations

from .time_utils import clock

from datetime import datetime
from typing import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .model_domains import ContentView, User

CONTENT_ENTITY_TYPES = {
    "event",
    "quest",
    "volunteer_task",
    "opportunity",
    "activity",
    "survey",
}


def _entity_type(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in CONTENT_ENTITY_TYPES:
        raise ValueError(f"Unsupported content view entity type: {value!r}")
    return normalized


async def record_content_view(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    *,
    user: User | None = None,
    tg_id: int | None = None,
    now: datetime | None = None,
) -> None:
    """Record one Telegram detail open without storing a row per click.

    Repeated opens by the same Telegram account increment ``view_count``.
    A unique constraint keeps the metric stable during concurrent callbacks.
    """
    kind = _entity_type(entity_type)
    viewer_tg_id = int(tg_id or (user.tg_id if user and user.tg_id else 0))
    if viewer_tg_id <= 0 or int(entity_id) <= 0:
        return
    stamp = now or clock.storage_utc()
    filters = (
        ContentView.entity_type == kind,
        ContentView.entity_id == int(entity_id),
        ContentView.tg_id == viewer_tg_id,
    )
    result = await session.execute(
        update(ContentView)
        .where(*filters)
        .values(
            view_count=ContentView.view_count + 1,
            last_viewed_at=stamp,
            user_id=user.id if user else ContentView.user_id,
        )
    )
    if result.rowcount:
        return
    try:
        async with session.begin_nested():
            session.add(ContentView(
                entity_type=kind,
                entity_id=int(entity_id),
                user_id=user.id if user else None,
                tg_id=viewer_tg_id,
                view_count=1,
                first_viewed_at=stamp,
                last_viewed_at=stamp,
            ))
            await session.flush()
    except IntegrityError:
        # A second callback may have created the unique row between UPDATE and
        # INSERT.  Increment that row instead of losing the view.
        await session.execute(
            update(ContentView)
            .where(*filters)
            .values(view_count=ContentView.view_count + 1, last_viewed_at=stamp)
        )


async def content_view_stats(
    session: AsyncSession,
    entity_type: str,
    entity_ids: Iterable[int] | None = None,
) -> dict[int, dict[str, int]]:
    kind = _entity_type(entity_type)
    stmt = (
        select(
            ContentView.entity_id,
            func.coalesce(func.sum(ContentView.view_count), 0),
            func.count(ContentView.id),
        )
        .where(ContentView.entity_type == kind)
        .group_by(ContentView.entity_id)
    )
    ids = [int(value) for value in (entity_ids or []) if int(value) > 0]
    if entity_ids is not None:
        if not ids:
            return {}
        stmt = stmt.where(ContentView.entity_id.in_(ids))
    rows = (await session.execute(stmt)).all()
    return {
        int(entity_id): {"views": int(views or 0), "unique": int(unique or 0)}
        for entity_id, views, unique in rows
    }


async def content_view_stat(session: AsyncSession, entity_type: str, entity_id: int) -> dict[str, int]:
    stats = await content_view_stats(session, entity_type, [entity_id])
    return stats.get(int(entity_id), {"views": 0, "unique": 0})
