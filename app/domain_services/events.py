from ..time_utils import clock
from .common import (
    AsyncSession, Event, EventRegistration, User, UserStatus, datetime, func, get_level, get_runtime_int, hashlib, label, normalize_event_xp, select, timedelta, token_urlsafe
)
from .gamification import add_xp, evaluate_automatic_badges, xp_total
from ..ambassadors import AMP_TEAM_ROLES
from ..event_schedule import event_end_utc

# Registration states that consume event capacity.
# Kept explicit here so the event domain does not depend on legacy wildcard exports.
EVENT_OCCUPIED_STATUSES = {"registered", "reserved", "checked_in", "attended"}
EVENT_REGISTRATION_STATUSES = {"registered", "waitlisted", "reserved", "checked_in", "attended", "no_show", "cancelled"}


def _event_modifier_xp(value: int | None) -> int:
    """Keep event bonuses/penalties configurable but proportionate to event XP."""
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(25, parsed))


def event_preregistration_bonus_eligible(event: Event, reg: EventRegistration) -> bool:
    """Return whether this registration was genuinely made before the event.

    A scanner-created registration is intentionally excluded even when the scanner
    is opened shortly before the advertised start time: the bonus rewards planning,
    not registration at the door. Legacy rows are evaluated from their timestamp.
    """
    if getattr(reg, "registration_source", "legacy") == "scanner":
        return False
    if not reg.registered_at:
        return False
    event_start_utc = clock.event_utc(event.starts_at)
    registered_utc = clock.from_storage_utc(reg.registered_at)
    return bool(event_start_utc and registered_utc and registered_utc < event_start_utc)


async def reconcile_event_registration_rewards(
    session: AsyncSession,
    event: Event,
    reg: EventRegistration,
    *,
    target_status: str,
    actor_user: User | None = None,
) -> dict[str, object]:
    """Make XP/hours match the chosen terminal/operational status exactly once.

    The registration stores amounts already applied. That makes attendance, bonus
    and no-show penalty reversible when a superadmin corrects a status later, while
    preserving an auditable XP transaction trail instead of deleting history.
    """
    if target_status not in EVENT_REGISTRATION_STATUSES:
        raise ValueError(f"Unsupported event registration status: {target_status}")
    user = await session.get(User, reg.user_id)
    if not user:
        return {"user": None, "total_xp": 0, "base_delta": 0, "bonus_delta": 0, "penalty_delta": 0, "hours_delta": 0.0, "leveled": False, "level_name": ""}

    event.xp_reward = normalize_event_xp(event.xp_reward)
    event.preregistration_bonus_xp = _event_modifier_xp(getattr(event, "preregistration_bonus_xp", 0))
    event.no_show_penalty_xp = _event_modifier_xp(getattr(event, "no_show_penalty_xp", 0))

    desired_base = event.xp_reward if target_status == "attended" else 0
    desired_bonus = event.preregistration_bonus_xp if (target_status == "attended" and event_preregistration_bonus_eligible(event, reg)) else 0
    desired_penalty = event.no_show_penalty_xp if target_status == "no_show" else 0
    desired_hours = max(0.0, float(event.volunteer_hours or 0)) if target_status == "attended" else 0.0

    base_delta = int(desired_base) - int(getattr(reg, "attendance_xp_awarded", 0) or 0)
    bonus_delta = int(desired_bonus) - int(getattr(reg, "preregistration_bonus_xp_awarded", 0) or 0)
    # Applied penalty is stored as a positive magnitude; XP transaction is negative.
    penalty_delta = int(getattr(reg, "no_show_penalty_xp_applied", 0) or 0) - int(desired_penalty)
    hours_delta = float(desired_hours) - float(getattr(reg, "volunteer_hours_awarded", 0) or 0)

    created_by = actor_user.id if actor_user else None
    leveled = False
    level_name = ""
    total = await xp_total(session, user.id)

    if base_delta:
        total, level_name, changed = await add_xp(
            session, user, base_delta,
            (f"Участь у події «{event.title}»" if base_delta > 0 else f"Коригування участі у події «{event.title}»"),
            category="event", created_by=created_by, event_id=event.id,
        )
        leveled = leveled or changed
    reg.attendance_xp_awarded = int(desired_base)

    if bonus_delta:
        total, level_name, changed = await add_xp(
            session, user, bonus_delta,
            (f"Бонус за попередню реєстрацію: «{event.title}»" if bonus_delta > 0 else f"Коригування бонусу реєстрації: «{event.title}»"),
            category="event_prereg_bonus", created_by=created_by, event_id=event.id,
        )
        leveled = leveled or changed
    reg.preregistration_bonus_xp_awarded = int(desired_bonus)

    if penalty_delta:
        total, level_name, changed = await add_xp(
            session, user, penalty_delta,
            (f"Повернення штрафу за неявку: «{event.title}»" if penalty_delta > 0 else f"Неявка без скасування: «{event.title}»"),
            category="event_no_show", created_by=created_by, event_id=event.id,
        )
        leveled = leveled or changed
    reg.no_show_penalty_xp_applied = int(desired_penalty)

    if hours_delta:
        user.volunteer_hours = max(0.0, float(user.volunteer_hours or 0) + hours_delta)
    reg.volunteer_hours_awarded = float(desired_hours)

    if not level_name:
        total = await xp_total(session, user.id)
        level_name = get_level(total)[0]
    await evaluate_automatic_badges(session, user)
    return {
        "user": user, "total_xp": total, "base_delta": base_delta, "bonus_delta": bonus_delta,
        "penalty_delta": penalty_delta, "hours_delta": hours_delta, "leveled": leveled, "level_name": level_name,
        "attendance_xp": int(desired_base), "preregistration_bonus_xp": int(desired_bonus),
        "no_show_penalty_xp": int(desired_penalty),
    }

async def create_event(
    session: AsyncSession,
    title: str,
    description: str,
    starts_at: datetime,
    location: str,
    xp_reward: int,
    volunteer_hours: float,
    created_by: int,
    preregistration_bonus_xp: int = 0,
    no_show_penalty_xp: int = 0,
    ends_at: datetime | None = None,
) -> Event:
    xp_reward = normalize_event_xp(xp_reward)
    event = Event(
        title=title,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at or (starts_at + timedelta(hours=2)),
        location=location,
        xp_reward=xp_reward,
        preregistration_bonus_xp=_event_modifier_xp(preregistration_bonus_xp),
        no_show_penalty_xp=_event_modifier_xp(no_show_penalty_xp),
        volunteer_hours=volunteer_hours,
        checkin_token=token_urlsafe(18),
        share_token=token_urlsafe(18),
        created_by=created_by,
    )
    session.add(event)
    await session.flush()
    return event


async def register_for_event(session: AsyncSession, user_id: int, event_id: int) -> EventRegistration:
    reg = await session.scalar(
        select(EventRegistration).where(EventRegistration.user_id == user_id, EventRegistration.event_id == event_id)
    )
    if reg:
        reg.status = "registered"
        reg.registered_at = clock.storage_utc()
        reg.registration_source = "participant"
        reg.waitlisted_at = None
        reg.reservation_expires_at = None
        reg.no_show_at = None
        return reg
    reg = EventRegistration(user_id=user_id, event_id=event_id, status="registered", registration_source="participant")
    session.add(reg)
    await session.flush()
    return reg


async def join_event_waitlist(session: AsyncSession, user_id: int, event_id: int, *, now: datetime | None = None) -> EventRegistration:
    """Place a participant in an event queue without consuming event capacity."""
    now = now or clock.storage_utc()
    reg = await session.scalar(
        select(EventRegistration).where(EventRegistration.user_id == user_id, EventRegistration.event_id == event_id)
    )
    if not reg:
        reg = EventRegistration(user_id=user_id, event_id=event_id, status="waitlisted", waitlisted_at=now, registration_source="participant")
        session.add(reg)
        await session.flush()
        return reg
    if reg.status == "attended":
        return reg
    reg.status = "waitlisted"
    reg.waitlisted_at = now
    reg.waitlist_promoted_at = None
    reg.reservation_expires_at = None
    reg.checkin_at = None
    reg.no_show_at = None
    return reg


async def accept_event_reservation(session: AsyncSession, user_id: int, event_id: int, *, now: datetime | None = None) -> tuple[EventRegistration | None, str]:
    """Confirm a two-hour waitlist reservation. Returns (registration, state)."""
    now = now or clock.storage_utc()
    reg = await session.scalar(
        select(EventRegistration).where(EventRegistration.user_id == user_id, EventRegistration.event_id == event_id)
    )
    if not reg or reg.status != "reserved":
        return reg, "not_reserved"
    if reg.reservation_expires_at and reg.reservation_expires_at <= now:
        reg.status = "waitlisted"
        reg.waitlisted_at = now
        reg.reservation_expires_at = None
        return reg, "expired"
    reg.status = "registered"
    reg.registered_at = now
    reg.reservation_expires_at = None
    return reg, "accepted"


async def process_event_operations(session: AsyncSession, *, now: datetime | None = None, event_id: int | None = None) -> dict[str, int]:
    """Maintain waitlist reservations and attendance terminal states.

    - Expired two-hour reservations return to the end of the queue.
    - Free capacity promotes the oldest queued participant and reserves a place for two hours.
    - Once an event is completed, participants who remained merely registered/reserved become no-shows.

    Notification Center provides durable Telegram delivery and deduplication.
    """
    from ..reliability import queue_telegram_delivery

    if now is None:
        now_utc = clock.now_utc()
        storage_now = clock.storage_utc(now_utc)
    elif now.tzinfo is None:
        # Legacy callers supplied naive UTC for scheduler/storage operations.
        storage_now = now
        now_utc = clock.from_storage_utc(now) or clock.now_utc()
    else:
        now_utc = clock.ensure_utc(now)
        storage_now = clock.storage_utc(now_utc)
    changed = {"expired_reservations": 0, "promoted_waitlist": 0, "cancelled_waitlist": 0, "no_show": 0, "no_show_penalty": 0}

    expired_stmt = select(EventRegistration).where(
        EventRegistration.status == "reserved",
        EventRegistration.reservation_expires_at.is_not(None),
        EventRegistration.reservation_expires_at <= storage_now,
    )
    if event_id is not None:
        expired_stmt = expired_stmt.where(EventRegistration.event_id == int(event_id))
    expired = list((await session.scalars(expired_stmt)).all())
    for reg in expired:
        reg.status = "waitlisted"
        reg.waitlisted_at = storage_now
        reg.reservation_expires_at = None
        changed["expired_reservations"] += 1
        user = await session.get(User, reg.user_id)
        event = await session.get(Event, reg.event_id)
        if user and event and user.status == UserStatus.ACTIVE.value and user.tg_id:
            await queue_telegram_delivery(
                session, user.tg_id,
                f"⏳ <b>Резерв місця завершився</b>\n\nДвогодинний резерв на подію «<b>{event.title}</b>» минув. "
                "Ми повернули тебе в чергу. Якщо звільниться наступне місце — бот повідомить автоматично.",
                source="event_waitlist",
                dedupe_key=f"event_waitlist_expired:{event.id}:{reg.id}:{int(now_utc.timestamp())//7200}",
            )

    events_stmt = select(Event).where(
        Event.capacity.is_not(None), Event.capacity > 0, Event.status.in_(["open", "closed", "postponed"])
    )
    if event_id is not None:
        events_stmt = events_stmt.where(Event.id == int(event_id))
    events = list((await session.scalars(events_stmt.order_by(Event.starts_at.asc()))).all())
    checkin_close_minutes = await get_runtime_int(session, "events.checkin_close_after_end_minutes")
    for event in events:
        # Do not promote people after the configured operational window has ended.
        event_finish_utc = event_end_utc(event)
        if event.cancelled_at or (event_finish_utc and event_finish_utc + timedelta(minutes=checkin_close_minutes) < now_utc):
            continue
        occupied = int(await session.scalar(
            select(func.count(EventRegistration.id)).where(
                EventRegistration.event_id == event.id,
                EventRegistration.status.in_(EVENT_OCCUPIED_STATUSES),
            )
        ) or 0)
        while occupied < int(event.capacity or 0):
            reg = await session.scalar(
                select(EventRegistration).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.status == "waitlisted",
                ).order_by(EventRegistration.waitlisted_at.asc().nullsfirst(), EventRegistration.id.asc())
            )
            if not reg:
                break
            user = await session.get(User, reg.user_id)
            if not user or user.status != UserStatus.ACTIVE.value:
                reg.status = "cancelled"
                changed["cancelled_waitlist"] += 1
                continue
            reg.status = "reserved"
            reg.waitlist_promoted_at = storage_now
            reservation_minutes = await get_runtime_int(session, "events.waitlist_reservation_minutes")
            reg.reservation_expires_at = storage_now + timedelta(minutes=reservation_minutes)
            changed["promoted_waitlist"] += 1
            occupied += 1
            await queue_telegram_delivery(
                session, user.tg_id,
                f"🎉 <b>Звільнилося місце!</b>\n\nНа подію «<b>{event.title}</b>» для тебе зарезервовано місце на <b>{reservation_minutes} хв</b>. "
                "Підтвердь його кнопкою нижче, інакше резерв перейде наступному учаснику в черзі.",
                source="event_waitlist",
                dedupe_key=f"event_waitlist_reserved:{event.id}:{reg.id}:{int(now_utc.timestamp())//7200}",
                button_text="✅ Підтвердити місце",
                callback_data=f"event_reserve_accept:{event.id}",
            )

    completed_stmt = select(Event.id).where(Event.status == "completed")
    if event_id is not None:
        completed_stmt = completed_stmt.where(Event.id == int(event_id))
    completed_events = list((await session.scalars(completed_stmt)).all())
    if completed_events:
        regs = list((await session.scalars(
            select(EventRegistration).where(
                EventRegistration.event_id.in_(completed_events),
                EventRegistration.status.in_(["registered", "reserved"]),
            )
        )).all())
        for reg in regs:
            event = await session.get(Event, reg.event_id)
            if not event:
                continue
            reward_change = await reconcile_event_registration_rewards(
                session, event, reg, target_status="no_show", actor_user=None
            )
            reg.status = "no_show"
            reg.no_show_at = storage_now
            reg.reservation_expires_at = None
            changed["no_show"] += 1
            if int(reward_change.get("penalty_delta") or 0) < 0:
                changed["no_show_penalty"] += 1
                user = reward_change.get("user")
                if user and user.status == UserStatus.ACTIVE.value and user.tg_id:
                    penalty = int(reward_change.get("no_show_penalty_xp") or 0)
                    await queue_telegram_delivery(
                        session, user.tg_id,
                        f"🚫 <b>Неявка на подію без скасування</b>\n\n«<b>{event.title}</b>»\n"
                        f"Оскільки реєстрацію не було скасовано до початку події, застосовано <b>-{penalty} XP</b>.\n\n"
                        "Якщо плани змінюються, скасовуй реєстрацію до початку — так місце зможе отримати інший учасник.",
                        source="event_no_show",
                        notification_type="event",
                        title=f"Неявка: {event.title}",
                        recipient_user_id=user.id, entity_type="event_registration", entity_id=reg.id,
                        dedupe_key=f"event_no_show_penalty:{event.id}:{reg.id}:{reg.no_show_penalty_xp_applied}",
                    )

    return changed


async def event_checkin_window(
    session: AsyncSession, event: Event, *, now: datetime | None = None
) -> dict[str, object]:
    """Return the operational check-in/attendance window for an event.

    Event schedule values remain legacy local-wall datetimes in storage, but the
    operational decision is made on an aware UTC timeline. Runtime settings make
    the window adjustable without a deploy.
    """
    before = await get_runtime_int(session, "events.checkin_open_before_minutes")
    after = await get_runtime_int(session, "events.checkin_close_after_end_minutes")
    event_start_utc = clock.event_utc(event.starts_at)
    event_finish_utc = event_end_utc(event)
    if event_start_utc is None or event_finish_utc is None:
        return {"state": "closed", "opens_at": None, "closes_at": None, "now": clock.local_wall(), "before_minutes": before, "after_minutes": after}
    if now is None:
        now_utc = clock.now_utc()
    elif now.tzinfo is None:
        # Explicit naive values in the legacy API represent event-local wall time.
        now_utc = clock.local_wall_to_utc(now)
    else:
        now_utc = clock.ensure_utc(now)
    opens_at_utc = event_start_utc - timedelta(minutes=before)
    closes_at_utc = event_finish_utc + timedelta(minutes=after)
    if now_utc < opens_at_utc:
        state = "too_early"
    elif now_utc > closes_at_utc:
        state = "closed"
    else:
        state = "open"
    return {
        "state": state,
        "opens_at": clock.local_wall(opens_at_utc),
        "closes_at": clock.local_wall(closes_at_utc),
        "now": clock.local_wall(now_utc),
        "opens_at_utc": opens_at_utc,
        "closes_at_utc": closes_at_utc,
        "now_utc": now_utc,
        "before_minutes": before,
        "after_minutes": after,
    }


async def checkin_for_event(
    session: AsyncSession, user_id: int, token: str, *, now: datetime | None = None
) -> tuple[Event | None, str]:
    event = await session.scalar(select(Event).where(Event.checkin_token == token))
    if not event or event.status not in {"open", "closed", "postponed"}:
        return None, "invalid"
    if getattr(event, "access_scope", "general") == "team":
        user = await session.get(User, user_id)
        if not user or user.status != UserStatus.ACTIVE.value or user.role not in AMP_TEAM_ROLES:
            return event, "forbidden"
    access = await event_checkin_window(session, event, now=now)
    if access["state"] == "too_early":
        return event, "too_early"
    if access["state"] == "closed":
        return event, "window_closed"
    reg = await session.scalar(
        select(EventRegistration).where(EventRegistration.user_id == user_id, EventRegistration.event_id == event.id)
    )
    checkin_at = clock.storage_utc(access["now_utc"])
    if not reg:
        reg = EventRegistration(
            user_id=user_id, event_id=event.id, status="checked_in",
            registered_at=checkin_at, registration_source="scanner",
        )
        session.add(reg)
    elif reg.status != "attended":
        if reg.status not in {"registered", "checked_in"}:
            reg.registered_at = checkin_at
            reg.registration_source = "scanner"
        reg.status = "checked_in"
    reg.checkin_at = checkin_at
    return event, "ok"


async def confirm_single_event_attendance(
    session: AsyncSession, event: Event, reg: EventRegistration, admin_user: User,
    *, override_reason: str | None = None, now: datetime | None = None,
) -> tuple[User, int, str, bool] | None:
    """Confirm attendance and award benefits exactly once.

    Ordinary confirmation is allowed only inside the configured attendance
    window. Staff may bypass it only by supplying a non-empty override reason;
    callers are responsible for writing that reason to the audit log.
    """
    if reg.event_id != event.id or reg.status == "attended":
        return None
    if reg.status != "checked_in":
        return None
    access = await event_checkin_window(session, event, now=now)
    override = (override_reason or "").strip()
    if access["state"] != "open" and len(override) < 5:
        return None

    # Lock/reload the registration on databases that support row locking. This
    # closes the common concurrent double-confirm path before XP is inserted.
    locked = await session.scalar(
        select(EventRegistration)
        .where(EventRegistration.id == reg.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not locked or locked.status == "attended" or locked.status != "checked_in":
        return None
    reg = locked
    user = await session.get(User, reg.user_id)
    if not user:
        return None
    reward_change = await reconcile_event_registration_rewards(
        session, event, reg, target_status="attended", actor_user=admin_user
    )
    total = int(reward_change["total_xp"])
    level = str(reward_change["level_name"])
    leveled = bool(reward_change["leveled"])
    reg.status = "attended"
    reg.confirmed_at = clock.storage_utc(access["now_utc"])
    reg.attendance_confirmed_by_user_id = admin_user.id
    if not reg.attendance_signature:
        raw_signature = "|".join([
            "AMP-ATTENDANCE-v1", str(event.id), str(reg.id), str(user.id),
            (reg.checkin_at or reg.confirmed_at).isoformat(), reg.confirmed_at.isoformat(), token_urlsafe(24),
        ])
        reg.attendance_signature = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()
        reg.attendance_signature_version = "sha256-v1"
        reg.attendance_signature_created_at = reg.confirmed_at
    return user, total, level, leveled


async def admin_scan_event_participant(
    session: AsyncSession,
    event_id: int,
    participant_id: int,
    admin_user: User,
    *,
    allow_register: bool = False,
) -> dict:
    """Resolve a participant QR/AMP-ID and confirm attendance from an admin scanner.

    The workflow is deliberately shared by Telegram scanner flows and can be used
    by web integrations. It preserves the existing idempotent attendance award.
    """
    event = await session.get(Event, event_id)
    if not event or event.cancelled_at or event.status in {"draft", "cancelled", "completed"}:
        return {"ok": False, "code": "event_unavailable", "message": "Відмітка для цієї події недоступна."}

    access = await event_checkin_window(session, event)
    if access["state"] != "open":
        return {
            "ok": False, "code": str(access["state"]),
            "message": "Відмітку ще не відкрито." if access["state"] == "too_early" else "Вікно відмітки та підтвердження участі вже закрито. Для винятку використайте ручне підтвердження з обов’язковою причиною.",
            "event": event, "window": access,
        }

    user = await session.get(User, participant_id)
    if not user:
        return {"ok": False, "code": "user_not_found", "message": "Учасника не знайдено."}
    if getattr(event, "access_scope", "general") == "team" and user.role not in AMP_TEAM_ROLES:
        return {"ok": False, "code": "team_event_forbidden", "message": "Ця подія доступна лише команді АМП.", "event": event, "user": user}
    if user.status != UserStatus.ACTIVE.value:
        return {
            "ok": False, "code": "user_inactive", "message": f"Акаунт учасника не активний: {label(user.status)}.",
            "event": event, "user": user,
        }

    reg = await session.scalar(select(EventRegistration).where(
        EventRegistration.event_id == event.id, EventRegistration.user_id == user.id
    ))
    if reg and reg.status == "attended":
        return {
            "ok": True, "code": "already_attended", "message": "Присутність уже була підтверджена раніше.",
            "event": event, "user": user, "registration": reg,
        }

    eligible = bool(reg and reg.status in {"registered", "reserved", "checked_in"})
    if not eligible and not allow_register:
        return {
            "ok": True, "code": "unregistered", "message": "Учасник не зареєстрований на цю подію.",
            "event": event, "user": user, "registration": reg, "requires_registration": True,
        }

    now = clock.storage_utc()
    if not reg:
        reg = EventRegistration(event_id=event.id, user_id=user.id, status="registered", registered_at=now, registration_source="scanner")
        session.add(reg)
        await session.flush()
    elif allow_register and reg.status not in {"registered", "reserved", "checked_in"}:
        reg.status = "registered"
        reg.registered_at = now
        reg.registration_source = "scanner"
        reg.waitlisted_at = None
        reg.reservation_expires_at = None
        reg.no_show_at = None

    if reg.status == "reserved":
        reg.registered_at = now
        reg.registration_source = "scanner"
        reg.reservation_expires_at = None
    if reg.status != "checked_in":
        reg.status = "checked_in"
        reg.checkin_at = now

    result = await confirm_single_event_attendance(session, event, reg, admin_user)
    if not result:
        return {"ok": False, "code": "confirm_failed", "message": "Не вдалося підтвердити присутність.", "event": event, "user": user, "registration": reg}
    confirmed_user, total, level_name, leveled = result
    return {
        "ok": True, "code": "confirmed", "message": "Присутність підтверджено",
        "event": event, "user": confirmed_user, "registration": reg,
        "total_xp": total, "level_name": level_name, "leveled": leveled,
        "xp": int(reg.attendance_xp_awarded or 0) + int(reg.preregistration_bonus_xp_awarded or 0),
        "base_xp": int(reg.attendance_xp_awarded or 0),
        "preregistration_bonus_xp": int(reg.preregistration_bonus_xp_awarded or 0),
        "hours": event.volunteer_hours,
    }

async def force_event_registration_status(
    session: AsyncSession,
    event: Event,
    reg: EventRegistration,
    target_status: str,
    admin_user: User,
) -> dict[str, object]:
    """Superadmin correction path for any registration status, independent of time.

    Rewards are reconciled to the resulting status rather than blindly appended,
    so repeated corrections remain financially/XP idempotent.
    """
    if target_status not in EVENT_REGISTRATION_STATUSES:
        raise ValueError("Unsupported event registration status")
    locked = await session.scalar(
        select(EventRegistration).where(EventRegistration.id == reg.id).with_for_update().execution_options(populate_existing=True)
    )
    if not locked or locked.event_id != event.id:
        raise ValueError("Registration does not belong to event")
    reg = locked
    previous_status = reg.status
    now = clock.storage_utc()

    # Reinstating a cancelled/queue-only record is a new commitment. A correction
    # from no_show back to attended keeps the original registration timestamp so
    # an earned pre-registration bonus is restored as well.
    if target_status in {"registered", "checked_in", "attended"} and previous_status in {"cancelled", "waitlisted", "reserved"}:
        reg.registered_at = now
        reg.registration_source = "admin"

    reward_change = await reconcile_event_registration_rewards(
        session, event, reg, target_status=target_status, actor_user=admin_user
    )

    reg.status = target_status
    if target_status == "registered":
        reg.checkin_at = None
        reg.confirmed_at = None
        reg.no_show_at = None
        reg.waitlisted_at = None
        reg.reservation_expires_at = None
    elif target_status == "waitlisted":
        reg.waitlisted_at = now
        reg.checkin_at = None
        reg.confirmed_at = None
        reg.no_show_at = None
        reg.reservation_expires_at = None
    elif target_status == "reserved":
        reg.waitlist_promoted_at = now
        reservation_minutes = await get_runtime_int(session, "events.waitlist_reservation_minutes")
        reg.reservation_expires_at = now + timedelta(minutes=reservation_minutes)
        reg.checkin_at = None
        reg.confirmed_at = None
        reg.no_show_at = None
    elif target_status == "checked_in":
        reg.checkin_at = now
        reg.confirmed_at = None
        reg.no_show_at = None
        reg.reservation_expires_at = None
    elif target_status == "attended":
        reg.checkin_at = reg.checkin_at or now
        reg.confirmed_at = now
        reg.no_show_at = None
        reg.reservation_expires_at = None
        reg.attendance_confirmed_by_user_id = admin_user.id
        if not reg.attendance_signature:
            raw_signature = "|".join([
                "AMP-ATTENDANCE-v1", str(event.id), str(reg.id), str(reg.user_id),
                (reg.checkin_at or now).isoformat(), now.isoformat(), token_urlsafe(24),
            ])
            reg.attendance_signature = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()
            reg.attendance_signature_version = "sha256-v1"
            reg.attendance_signature_created_at = now
    elif target_status == "no_show":
        reg.no_show_at = now
        reg.checkin_at = None
        reg.confirmed_at = None
        reg.reservation_expires_at = None
    elif target_status == "cancelled":
        reg.checkin_at = None
        reg.confirmed_at = None
        reg.no_show_at = None
        reg.reservation_expires_at = None

    if target_status != "attended":
        reg.attendance_confirmed_by_user_id = None
        reg.attendance_signature = None
        reg.attendance_signature_version = None
        reg.attendance_signature_created_at = None

    reward_change["previous_status"] = previous_status
    reward_change["target_status"] = target_status
    return reward_change


async def confirm_event_attendance(session: AsyncSession, event: Event, admin_user: User, *, override_reason: str | None = None, now: datetime | None = None) -> tuple[int, list[tuple[User, int, str, bool]]]:
    regs = (
        await session.scalars(
            select(EventRegistration).where(EventRegistration.event_id == event.id, EventRegistration.status == "checked_in")
        )
    ).all()
    results: list[tuple[User, int, str, bool]] = []
    for reg in regs:
        result = await confirm_single_event_attendance(session, event, reg, admin_user, override_reason=override_reason, now=now)
        if result:
            results.append(result)
    return len(results), results


