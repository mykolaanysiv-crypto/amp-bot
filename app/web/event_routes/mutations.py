from __future__ import annotations

from fastapi.responses import JSONResponse
from urllib.parse import parse_qs, urlparse
import re
from app.web.dependencies import (
    APP_VERSION, AuditLog, BytesIO, Event, EventFeedback, EventRegistration, File, Form, HTMLResponse, HTTPException, Path, RedirectResponse, Request, StreamingResponse, UploadFile, User, UserRole, UserStatus, WebStaffAccount, XPTransaction, compose_event_datetime, confirm_event_attendance, confirm_single_event_attendance, ctx, db, delete, delete_image, event_registration_status_label, export_event_participants_excel, export_event_participants_pdf, func, guard, guard_permission, has_web_permission, label, log_audit, logging, normalize_event_xp, notify_telegram, opt_int, or_, process_event_operations, qrcode, queue_telegram_delivery, quote, save_image, select, settings, store_file_bytes, templates, timedelta, token_urlsafe, update
)
from app.media import load_file_bytes
from app.event_documents import fill_registration_template
from app.telegram_webapp import validate_webapp_init_data
from app.services import admin_scan_event_participant, event_checkin_window
from app.time_utils import clock
from app.observability import log_extra
from app.content_views import content_view_stat, content_view_stats
from app.web.dependencies import _refresh_lifecycle
from app.ambassadors import AMP_TEAM_ROLES
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

from .context import router


@router.post("/admin/events/create")
async def event_create(
    request: Request, title: str = Form(...), day: int = Form(...), month: int = Form(...), year: int = Form(...),
    event_time: str = Form(...), location: str = Form("АМП"), description: str = Form(""), xp_reward: int = Form(10),
    preregistration_bonus_xp: int = Form(5), no_show_penalty_xp: int = Form(5),
    volunteer_hours: float = Form(0), capacity: str = Form(""), status: str = Form("open"), access_scope: str = Form("general"), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    starts_at = compose_event_datetime(day, month, year, event_time)
    image = await save_image(photo, "events")
    campaign_id=None
    async with db.session_factory() as session:
        xp_reward = normalize_event_xp(xp_reward)
        e = Event(
            title=title.strip(), description=description.strip(), starts_at=starts_at, location=location.strip() or "АМП",
            xp_reward=xp_reward, preregistration_bonus_xp=max(0, min(25, int(preregistration_bonus_xp))),
            no_show_penalty_xp=max(0, min(25, int(no_show_penalty_xp))),
            volunteer_hours=max(0, volunteer_hours), capacity=opt_int(capacity), status=status if status in {"draft", "open", "closed"} else "open",
            access_scope=access_scope if access_scope in {"general", "team"} else "general",
            checkin_token=token_urlsafe(18), share_token=token_urlsafe(18), image_path=image,
        )
        session.add(e)
        await session.flush()
        await log_audit(session, "web_event_create", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=e.id, details=e.title)
        if e.status=="open":
            user_stmt=select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None))
            if e.access_scope == "team": user_stmt=user_stmt.where(User.role.in_(AMP_TEAM_ROLES))
            users=list((await session.scalars(user_stmt)).all())
            text=(f"📅 <b>Нова подія в АМП</b>\n\n<b>{e.title}</b>\n🕒 {e.starts_at.strftime('%d.%m.%Y %H:%M')}\n📍 {e.location}\n"
                  f"⚡ За участь: {e.xp_reward} XP\n🎟 Бонус за попередню реєстрацію: +{e.preregistration_bonus_xp} XP\n"
                  f"🚫 Неявка без скасування до початку: -{e.no_show_penalty_xp} XP\n\n"
                  "Відкрий у боті розділ «📅 Події», щоб переглянути деталі та зареєструватися.")
            campaign_id=await _queue_system_broadcast(session,users,text,author_label=request.session.get("admin_name","web"),audience_label=f"Нова подія: {e.title}",template_code="event_created")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/events", 303)

@router.post("/admin/events/{event_id}/update")
async def event_update(
    request: Request, event_id: int, title: str = Form(...), day: int = Form(...), month: int = Form(...), year: int = Form(...),
    event_time: str = Form(...), location: str = Form("АМП"), description: str = Form(""), xp_reward: int = Form(10),
    preregistration_bonus_xp: int = Form(5), no_show_penalty_xp: int = Form(5),
    volunteer_hours: float = Form(0), capacity: str = Form(""), status: str = Form("open"), access_scope: str = Form("general"),
    remove_image: str | None = Form(None), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    starts_at = compose_event_datetime(day, month, year, event_time)
    campaign_id=None
    async with db.session_factory() as session:
        e = await session.get(Event, event_id)
        if e:
            was_public = e.status in {"open","postponed"}
            e.title = title.strip(); e.starts_at = starts_at; e.location = location.strip() or "АМП"; e.description = description.strip()
            e.xp_reward = normalize_event_xp(xp_reward)
            e.preregistration_bonus_xp = max(0, min(25, int(preregistration_bonus_xp)))
            e.no_show_penalty_xp = max(0, min(25, int(no_show_penalty_xp)))
            e.volunteer_hours = max(0, volunteer_hours); e.capacity = opt_int(capacity)
            requested_scope = access_scope if access_scope in {"general", "team"} else "general"
            if requested_scope == "team" and getattr(e, "access_scope", "general") != "team":
                non_team_reg = await session.scalar(
                    select(EventRegistration.id)
                    .join(User, User.id == EventRegistration.user_id)
                    .where(EventRegistration.event_id == e.id, EventRegistration.status != "cancelled", User.role.not_in(AMP_TEAM_ROLES))
                    .limit(1)
                )
                if non_team_reg:
                    raise HTTPException(status_code=409, detail="Не можна зробити подію закритою для команди: на неї вже зареєстровані звичайні учасники.")
            e.access_scope = requested_scope
            if not e.cancelled_at and e.status not in {"postponed", "completed", "cancelled"} and status in {"draft", "open", "closed"}:
                e.status = status
            if remove_image:
                await delete_image(e.image_path); e.image_path = None
            img = await save_image(photo, "events")
            if img:
                await delete_image(e.image_path); e.image_path = img
            await log_audit(session, "web_event_update", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=e.id, details=e.title)
            if not was_public and e.status=="open":
                user_stmt=select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None))
                if e.access_scope == "team": user_stmt=user_stmt.where(User.role.in_(AMP_TEAM_ROLES))
                users=list((await session.scalars(user_stmt)).all())
                campaign_id=await _queue_system_broadcast(
                    session, users,
                    f"📅 <b>Нова подія в АМП</b>\n\n<b>{e.title}</b>\n🕒 {e.starts_at.strftime('%d.%m.%Y %H:%M')}\n📍 {e.location}\n"
                    f"⚡ За участь: {e.xp_reward} XP\n🎟 Бонус за попередню реєстрацію: +{e.preregistration_bonus_xp} XP\n"
                    f"🚫 Неявка без скасування до початку: -{e.no_show_penalty_xp} XP\n\nВідкрий «📅 Події» у боті, щоб зареєструватися.",
                    author_label=request.session.get("admin_name","web"), audience_label=f"Нова подія: {e.title}", template_code="event_published"
                )
            await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/events", 303)


def _event_feedback_next_step(feedback: EventFeedback) -> tuple[str | None, str | None]:
    """Return the next unanswered micro-feedback question for a participant."""
    if feedback.rating is None:
        return "event_feedback_rating", "Обери оцінку від 1 до 5."
    if feedback.useful is None:
        return "event_feedback_useful", "Було корисно?"
    if feedback.new_knowledge is None:
        return "event_feedback_knowledge", "Дізнався/дізналася щось нове?"
    if feedback.felt_safe is None:
        return "event_feedback_safe", "Почувався/почувалася безпечно?"
    if feedback.would_return is None:
        return "event_feedback_return", "Хочеш прийти на події АМП ще?"
    return None, None


@router.post("/admin/events/{event_id}/feedback/resend")
async def event_feedback_resend(request: Request, event_id: int):
    """Manually resend the next feedback question to attended participants who have not completed it."""
    if r := guard_permission(request, "events.edit"):
        return r

    now = clock.storage_utc()
    # One explicit resend batch per minute prevents accidental double-click duplicates,
    # while still allowing an administrator to repeat the mailing later if needed.
    batch_key = now.strftime("%Y%m%d%H%M")
    sent = 0
    skipped_completed = 0

    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено.")
        if event.cancelled_at or event.status == "cancelled":
            raise HTTPException(status_code=409, detail="Для скасованої події розсилку відгуку недоступно.")

        rows = (await session.execute(
            select(EventRegistration, User)
            .join(User, User.id == EventRegistration.user_id)
            .where(
                EventRegistration.event_id == event.id,
                EventRegistration.status == "attended",
                User.status == UserStatus.ACTIVE.value,
                User.tg_id.is_not(None),
            )
            .order_by(EventRegistration.confirmed_at.asc().nullsfirst(), EventRegistration.id.asc())
        )).all()

        user_ids = [user.id for _, user in rows]
        feedback_by_user: dict[int, EventFeedback] = {}
        if user_ids:
            feedback_by_user = {
                feedback.user_id: feedback
                for feedback in (await session.scalars(
                    select(EventFeedback).where(
                        EventFeedback.event_id == event.id,
                        EventFeedback.user_id.in_(user_ids),
                    )
                )).all()
            }

        for _registration, user in rows:
            feedback = feedback_by_user.get(user.id)
            if feedback and feedback.status == "completed":
                skipped_completed += 1
                continue

            if not feedback:
                feedback = EventFeedback(
                    event_id=event.id, user_id=user.id, status="pending",
                    prompted_at=now, created_at=now, updated_at=now,
                )
                session.add(feedback)
                await session.flush()
                feedback_by_user[user.id] = feedback
            else:
                if feedback.prompted_at is None:
                    feedback.prompted_at = now
                feedback.updated_at = now

            entity_type, question = _event_feedback_next_step(feedback)
            if not entity_type:
                feedback.status = "completed"
                feedback.completed_at = feedback.completed_at or now
                feedback.updated_at = now
                skipped_completed += 1
                continue

            intro = "Повторне нагадування" if feedback.rating is not None or feedback.status == "in_progress" else "Запит відгуку"
            await queue_telegram_delivery(
                session, user.tg_id,
                f"⭐ <b>{intro} про подію «{event.title}»</b>\n\n"
                f"{question}\n\n"
                "Ваш відгук займе менше хвилини та допоможе АМП покращувати наступні активності.",
                source="event_feedback_manual_resend",
                notification_type="event",
                title=f"Відгук: {event.title}",
                recipient_user_id=user.id,
                entity_type=entity_type, entity_id=feedback.id,
                dedupe_key=f"event_feedback:manual:{event.id}:{user.id}:{batch_key}",
            )
            sent += 1

        await log_audit(
            session, "web_event_feedback_resend",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="event", entity_id=event.id,
            details=f"Повторна розсилка відгуку: у черзі {sent}; уже завершили {skipped_completed}; підтверджених учасників {len(rows)}.",
        )
        await session.commit()

    notice = "feedback_resent" if sent else "feedback_none"
    return RedirectResponse(
        f"/admin/events/{event_id}?notice={notice}&sent={sent}#event-feedback",
        status_code=303,
    )

@router.post("/admin/events/{event_id}/postpone")
async def event_postpone(request: Request, event_id: int, reason: str = Form(...), day: int = Form(...), month: int = Form(...), year: int = Form(...), event_time: str = Form(...)):
    if r := guard(request): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину перенесення події.")
    new_at = compose_event_datetime(day, month, year, event_time)
    if clock.local_wall_to_utc(new_at) <= clock.now_utc():
        raise HTTPException(status_code=400, detail="Нова дата події має бути в майбутньому.")
    campaign_id = None
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event: raise HTTPException(status_code=404, detail="Подію не знайдено.")
        if event.cancelled_at or event.status == "cancelled": raise HTTPException(status_code=409, detail="Скасовану подію не можна переносити.")
        users = list((await session.scalars(select(User).join(EventRegistration, EventRegistration.user_id==User.id).where(EventRegistration.event_id==event.id, EventRegistration.status!="cancelled").distinct())).all())
        event.starts_at = new_at; event.status = "postponed"; event.postponed_reason = reason; event.postponed_at = clock.storage_utc(); await session.execute(update(EventRegistration).where(EventRegistration.event_id==event.id).values(reminder_1h_sent_at=None))
        campaign_id = await _queue_system_broadcast(session, users, _postponed_notice_text("Подію", event.title, new_at, reason), author_label=request.session.get("admin_name","web"), audience_label=f"Учасники перенесеної події: {event.title}", template_code="event_postponed")
        await log_audit(session,"web_event_postpone",actor_label=request.session.get("admin_name","web"),entity_type="event",entity_id=event.id,details=f"Нова дата {new_at}; причина: {reason}; повідомлень: {len(users)}")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/events/{event_id}",303)

@router.post("/admin/events/{event_id}/cancel")
async def event_cancel(request: Request, event_id: int, reason: str = Form(...)):
    if r := guard(request): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину скасування події.")
    campaign_id: int | None = None
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено.")
        if event.cancelled_at or event.status == "cancelled":
            raise HTTPException(status_code=409, detail="Подію вже скасовано.")
        if event.status == "completed":
            raise HTTPException(status_code=409, detail="Завершену подію не можна скасувати.")
        users = list((await session.scalars(
            select(User)
            .join(EventRegistration, EventRegistration.user_id == User.id)
            .where(EventRegistration.event_id == event.id, EventRegistration.status != "cancelled")
            .distinct()
        )).all())
        event.status = "cancelled"
        event.cancellation_reason = reason
        event.cancelled_at = clock.storage_utc()
        campaign_id = await _queue_system_broadcast(
            session, users, _entity_notice_text("Подію", event.title, reason),
            author_label=request.session.get("admin_name", "web"),
            audience_label=f"Учасники скасованої події: {event.title}",
            template_code="event_cancelled",
        )
        await log_audit(
            session, "web_event_cancel", actor_label=request.session.get("admin_name", "web"),
            entity_type="event", entity_id=event.id,
            details=f"Скасовано подію «{event.title}». Причина: {reason}. Повідомлень у черзі: {len(users)}.",
        )
        await session.commit()
    if campaign_id:
        _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

@router.post("/admin/events/{event_id}/delete")
async def event_delete(request: Request, event_id: int, reason: str = Form(...)):
    if r := guard_permission(request, "events.delete"): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину видалення події.")
    campaign_id: int | None = None
    image_path: str | None = None
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено.")
        users = list((await session.scalars(
            select(User)
            .join(EventRegistration, EventRegistration.user_id == User.id)
            .where(EventRegistration.event_id == event.id, EventRegistration.status != "cancelled")
            .distinct()
        )).all())
        title = event.title
        image_path = event.image_path
        campaign_id = await _queue_system_broadcast(
            session, users, _entity_notice_text("Подію", title, reason, deleted=True),
            author_label=request.session.get("admin_name", "web"),
            audience_label=f"Учасники видаленої події: {title}",
            template_code="event_deleted",
        )
        # Preserve already-earned XP while removing the event itself.
        await session.execute(update(XPTransaction).where(XPTransaction.event_id == event.id).values(event_id=None))
        await session.execute(delete(EventRegistration).where(EventRegistration.event_id == event.id))
        await log_audit(
            session, "web_event_delete", actor_label=request.session.get("admin_name", "web"),
            entity_type="event", entity_id=event.id,
            details=f"Видалено подію «{title}». Причина: {reason}. Повідомлень у черзі: {len(users)}.",
        )
        await session.delete(event)
        await session.commit()
    if image_path:
        await delete_image(image_path)
    if campaign_id:
        _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/events", status_code=303)
