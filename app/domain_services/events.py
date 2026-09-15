from .common import *  # noqa: F401,F403
from .gamification import add_xp, evaluate_automatic_badges

# Registration states that consume event capacity.
# Kept explicit here so the event domain does not depend on legacy wildcard exports.
EVENT_OCCUPIED_STATUSES = {"registered", "reserved", "checked_in", "attended"}

async def create_event(
    session: AsyncSession,
    title: str,
    description: str,
    starts_at: datetime,
    location: str,
    xp_reward: int,
    volunteer_hours: float,
    created_by: int,
) -> Event:
    xp_reward = normalize_event_xp(xp_reward)
    event = Event(
        title=title,
        description=description,
        starts_at=starts_at,
        location=location,
        xp_reward=xp_reward,
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
        reg.registered_at = datetime.utcnow()
        reg.waitlisted_at = None
        reg.reservation_expires_at = None
        reg.no_show_at = None
        return reg
    reg = EventRegistration(user_id=user_id, event_id=event_id, status="registered")
    session.add(reg)
    await session.flush()
    return reg


async def join_event_waitlist(session: AsyncSession, user_id: int, event_id: int, *, now: datetime | None = None) -> EventRegistration:
    """Place a participant in an event queue without consuming event capacity."""
    now = now or datetime.utcnow()
    reg = await session.scalar(
        select(EventRegistration).where(EventRegistration.user_id == user_id, EventRegistration.event_id == event_id)
    )
    if not reg:
        reg = EventRegistration(user_id=user_id, event_id=event_id, status="waitlisted", waitlisted_at=now)
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
    now = now or datetime.utcnow()
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

    explicit_now = now
    now = now or datetime.utcnow()
    event_now = explicit_now or event_local_now()
    changed = {"expired_reservations": 0, "promoted_waitlist": 0, "cancelled_waitlist": 0, "no_show": 0}

    expired_stmt = select(EventRegistration).where(
        EventRegistration.status == "reserved",
        EventRegistration.reservation_expires_at.is_not(None),
        EventRegistration.reservation_expires_at <= now,
    )
    if event_id is not None:
        expired_stmt = expired_stmt.where(EventRegistration.event_id == int(event_id))
    expired = list((await session.scalars(expired_stmt)).all())
    for reg in expired:
        reg.status = "waitlisted"
        reg.waitlisted_at = now
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
                dedupe_key=f"event_waitlist_expired:{event.id}:{reg.id}:{int(now.timestamp())//7200}",
            )

    events_stmt = select(Event).where(
        Event.capacity.is_not(None), Event.capacity > 0, Event.status.in_(["open", "closed", "postponed"])
    )
    if event_id is not None:
        events_stmt = events_stmt.where(Event.id == int(event_id))
    events = list((await session.scalars(events_stmt.order_by(Event.starts_at.asc()))).all())
    checkin_close_minutes = await get_runtime_int(session, "events.checkin_close_after_minutes")
    for event in events:
        # Do not promote people after the configured operational window has ended.
        if event.cancelled_at or (event.starts_at and event.starts_at + timedelta(minutes=checkin_close_minutes) < event_now):
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
            reg.waitlist_promoted_at = now
            reservation_minutes = await get_runtime_int(session, "events.waitlist_reservation_minutes")
            reg.reservation_expires_at = now + timedelta(minutes=reservation_minutes)
            changed["promoted_waitlist"] += 1
            occupied += 1
            await queue_telegram_delivery(
                session, user.tg_id,
                f"🎉 <b>Звільнилося місце!</b>\n\nНа подію «<b>{event.title}</b>» для тебе зарезервовано місце на <b>{reservation_minutes} хв</b>. "
                "Підтвердь його кнопкою нижче, інакше резерв перейде наступному учаснику в черзі.",
                source="event_waitlist",
                dedupe_key=f"event_waitlist_reserved:{event.id}:{reg.id}:{int(now.timestamp())//7200}",
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
            reg.status = "no_show"
            reg.no_show_at = now
            reg.reservation_expires_at = None
            changed["no_show"] += 1

    return changed


async def event_checkin_window(
    session: AsyncSession, event: Event, *, now: datetime | None = None
) -> dict[str, object]:
    """Return the operational check-in/attendance window for an event.

    Datetimes in the current schema are naive and are compared consistently with
    the rest of the application. Runtime settings make the window adjustable
    without a deploy.
    """
    now = now or event_local_now()
    before = await get_runtime_int(session, "events.checkin_open_before_minutes")
    after = await get_runtime_int(session, "events.checkin_close_after_minutes")
    opens_at = event.starts_at - timedelta(minutes=before)
    closes_at = event.starts_at + timedelta(minutes=after)
    if now < opens_at:
        state = "too_early"
    elif now > closes_at:
        state = "closed"
    else:
        state = "open"
    return {"state": state, "opens_at": opens_at, "closes_at": closes_at, "now": now, "before_minutes": before, "after_minutes": after}


async def checkin_for_event(
    session: AsyncSession, user_id: int, token: str, *, now: datetime | None = None
) -> tuple[Event | None, str]:
    event = await session.scalar(select(Event).where(Event.checkin_token == token))
    if not event or event.status not in {"open", "closed", "postponed"}:
        return None, "invalid"
    access = await event_checkin_window(session, event, now=now)
    if access["state"] == "too_early":
        return event, "too_early"
    if access["state"] == "closed":
        return event, "window_closed"
    reg = await session.scalar(
        select(EventRegistration).where(EventRegistration.user_id == user_id, EventRegistration.event_id == event.id)
    )
    if not reg:
        reg = EventRegistration(user_id=user_id, event_id=event.id, status="checked_in")
        session.add(reg)
    elif reg.status != "attended":
        reg.status = "checked_in"
    reg.checkin_at = access["now"]
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
    event.xp_reward = normalize_event_xp(event.xp_reward)
    total, level, leveled = await add_xp(
        session,
        user,
        event.xp_reward,
        f"Участь у події «{event.title}»",
        category="event",
        created_by=admin_user.id,
        event_id=event.id,
    )
    user.volunteer_hours += event.volunteer_hours
    reg.status = "attended"
    reg.confirmed_at = access["now"]
    reg.attendance_confirmed_by_user_id = admin_user.id
    if not reg.attendance_signature:
        raw_signature = "|".join([
            "AMP-ATTENDANCE-v1", str(event.id), str(reg.id), str(user.id),
            (reg.checkin_at or reg.confirmed_at).isoformat(), reg.confirmed_at.isoformat(), token_urlsafe(24),
        ])
        reg.attendance_signature = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()
        reg.attendance_signature_version = "sha256-v1"
        reg.attendance_signature_created_at = reg.confirmed_at
    await evaluate_automatic_badges(session, user)
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

    now = event_local_now()
    if not reg:
        reg = EventRegistration(event_id=event.id, user_id=user.id, status="registered", registered_at=now)
        session.add(reg)
        await session.flush()
    elif allow_register and reg.status not in {"registered", "reserved", "checked_in"}:
        reg.status = "registered"
        reg.registered_at = now
        reg.waitlisted_at = None
        reg.reservation_expires_at = None
        reg.no_show_at = None

    if reg.status == "reserved":
        reg.registered_at = now
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
        "xp": event.xp_reward, "hours": event.volunteer_hours,
    }


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


