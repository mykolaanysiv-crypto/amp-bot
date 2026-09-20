from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime

from sqlalchemy import select

from .ambassadors import AMP_TEAM_ROLES
from .model_domains import EventRegistration, Giveaway, GiveawayEntry, GiveawayPrize, GiveawayWinner, User, UserRole, UserStatus
from .time_utils import clock

GIVEAWAY_AUDIENCE_TYPES = {"all", "team", "event", "roles", "users"}
GIVEAWAY_PARTICIPATION_MODES = {"automatic", "task"}
EVENT_AUDIENCE_STATUSES = {"registered", "reserved", "checked_in", "attended"}
ALL_USER_ROLES = {
    UserRole.PARTICIPANT.value,
    UserRole.AMBASSADOR.value,
    UserRole.COORDINATOR.value,
    UserRole.ADMIN.value,
    UserRole.SUPERADMIN.value,
}


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def audience_label(giveaway: Giveaway) -> str:
    kind = giveaway.audience_type or "all"
    if kind == "all":
        return "Усі активні учасники"
    if kind == "team":
        return "Команда АМП"
    if kind == "event":
        return f"Учасники події №{giveaway.audience_value or '—'}"
    if kind == "roles":
        labels = {
            "participant": "Учасники", "ambassador": "АМПасадори", "coordinator": "Координатори",
            "admin": "Адміністратори", "superadmin": "Суперадміністратори",
        }
        return ", ".join(labels.get(str(v), str(v)) for v in _json_list(giveaway.audience_value)) or "Обрані ролі"
    if kind == "users":
        return "Обрані учасники"
    return kind


def participation_label(giveaway: Giveaway) -> str:
    return "Автоматична участь" if giveaway.participation_mode == "automatic" else "Участь після виконання завдання"


def is_open_now(giveaway: Giveaway, *, now: datetime | None = None) -> bool:
    if giveaway.status != "active":
        return False
    current = now or clock.storage_utc()
    if giveaway.starts_at and current < giveaway.starts_at:
        return False
    if giveaway.ends_at and current > giveaway.ends_at:
        return False
    return True


async def eligible_user_ids(session, giveaway: Giveaway) -> list[int]:
    """Resolve the current eligible audience, always restricted to active users."""
    stmt = select(User.id).where(User.status == UserStatus.ACTIVE.value)
    kind = (giveaway.audience_type or "all").strip()
    if kind == "team":
        stmt = stmt.where(User.role.in_(AMP_TEAM_ROLES))
    elif kind == "event":
        try:
            event_id = int(giveaway.audience_value or 0)
        except (TypeError, ValueError):
            return []
        stmt = (
            select(User.id)
            .join(EventRegistration, EventRegistration.user_id == User.id)
            .where(
                User.status == UserStatus.ACTIVE.value,
                EventRegistration.event_id == event_id,
                EventRegistration.status.in_(EVENT_AUDIENCE_STATUSES),
            )
        )
    elif kind == "roles":
        roles = [str(v) for v in _json_list(giveaway.audience_value) if str(v) in ALL_USER_ROLES]
        if not roles:
            return []
        stmt = stmt.where(User.role.in_(roles))
    elif kind == "users":
        ids = []
        for value in _json_list(giveaway.audience_value):
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if not ids:
            return []
        stmt = stmt.where(User.id.in_(ids))
    elif kind != "all":
        return []
    return sorted(set(int(v) for v in (await session.scalars(stmt)).all()))


async def user_is_eligible(session, giveaway: Giveaway, user: User) -> bool:
    if not user or user.status != UserStatus.ACTIVE.value:
        return False
    ids = await eligible_user_ids(session, giveaway)
    return int(user.id) in set(ids)


async def approved_draw_user_ids(session, giveaway: Giveaway) -> list[int]:
    eligible = set(await eligible_user_ids(session, giveaway))
    if giveaway.participation_mode == "automatic":
        return sorted(eligible)
    approved = set(int(v) for v in (await session.scalars(
        select(GiveawayEntry.user_id).where(
            GiveawayEntry.giveaway_id == giveaway.id,
            GiveawayEntry.status == "approved",
        )
    )).all())
    return sorted(eligible & approved)


async def materialize_automatic_entries(session, giveaway: Giveaway, user_ids: list[int]) -> None:
    if giveaway.participation_mode != "automatic":
        return
    existing = set(int(v) for v in (await session.scalars(
        select(GiveawayEntry.user_id).where(GiveawayEntry.giveaway_id == giveaway.id)
    )).all())
    now = clock.storage_utc()
    for user_id in user_ids:
        if user_id in existing:
            continue
        session.add(GiveawayEntry(
            giveaway_id=giveaway.id,
            user_id=user_id,
            source="automatic",
            status="approved",
            submitted_at=now,
            reviewed_at=now,
            reviewed_by="Система АМП",
            created_at=now,
            updated_at=now,
        ))


async def prize_units(session, giveaway_id: int) -> list[GiveawayPrize]:
    prizes = list((await session.scalars(
        select(GiveawayPrize)
        .where(GiveawayPrize.giveaway_id == giveaway_id)
        .order_by(GiveawayPrize.sort_order.asc(), GiveawayPrize.id.asc())
    )).all())
    units: list[GiveawayPrize] = []
    for prize in prizes:
        units.extend([prize] * max(0, int(prize.quantity or 0)))
    return units


async def run_draw(session, giveaway: Giveaway) -> tuple[list[GiveawayWinner], str]:
    """Perform one auditable, deterministic draw using a cryptographic seed.

    Each participant can win at most one prize in a draw. The seed is stored so
    the randomized order can be reproduced for audit, while ``secrets`` provides
    the unpredictable seed material.
    """
    existing = list((await session.scalars(
        select(GiveawayWinner).where(GiveawayWinner.giveaway_id == giveaway.id)
    )).all())
    if existing:
        return existing, giveaway.draw_seed or ""

    users = await approved_draw_user_ids(session, giveaway)
    units = await prize_units(session, giveaway.id)
    if not units:
        raise ValueError("У розіграші немає подарунків із доступною кількістю.")
    if len(users) < len(units):
        raise ValueError(f"Потрібно щонайменше {len(units)} допущених учасників, зараз {len(users)}.")

    await materialize_automatic_entries(session, giveaway, users)
    seed = secrets.token_hex(32)
    shuffled = sorted(
        users,
        key=lambda user_id: hashlib.sha256(f"{seed}:{user_id}".encode("utf-8")).digest(),
    )
    now = clock.storage_utc()
    winners: list[GiveawayWinner] = []
    for index, prize in enumerate(units, start=1):
        row = GiveawayWinner(
            giveaway_id=giveaway.id,
            prize_id=prize.id,
            user_id=shuffled[index - 1],
            draw_order=index,
            created_at=now,
        )
        session.add(row)
        winners.append(row)
    giveaway.status = "drawn"
    giveaway.drawn_at = now
    giveaway.draw_seed = seed
    giveaway.draw_algorithm = "sha256-seeded-order-v1"
    giveaway.updated_at = now
    await session.flush()
    return winners, seed
