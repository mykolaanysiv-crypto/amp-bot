from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from urllib.parse import parse_qs, urlparse
import re
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.media import load_file_bytes
from app.event_documents import fill_registration_template
from app.telegram_webapp import validate_webapp_init_data
from app.services import admin_scan_event_participant, event_checkin_window
from app.time_utils import clock
from app.observability import log_extra
from app.content_views import content_view_stat, content_view_stats
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()


@router.get("/tg/event-scanner/{event_id}", response_class=HTMLResponse)
async def telegram_miniapp_event_scanner(request: Request, event_id: int):
    """Telegram Mini App shell for continuous native QR scanning."""
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event or event.cancelled_at or event.status not in {"open", "closed", "postponed"}:
            return HTMLResponse("QR-сканер для цієї події недоступний", status_code=409)
    response = templates.TemplateResponse(
        request=request,
        name="telegram_event_scanner.html",
        context={"request": request, "event": event, "app_version": APP_VERSION},
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/tg/event-scanner/{event_id}/scan")
async def telegram_miniapp_event_scan(request: Request, event_id: int):
    """Process one scan from the Telegram-native continuous QR popup.

    Authentication comes from signed Telegram Mini App initData, not from the
    ordinary web admin cookie.  Every scan also queues an operator receipt in
    the bot chat while the camera stays open for the next badge.
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Некоректний запит."}, status_code=400)
    init_data = str(payload.get("init_data") or "")
    code_text = str(payload.get("code") or "").strip()
    scan_id = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("scan_id") or ""))[:80]
    tg_user = validate_webapp_init_data(init_data, settings.bot_token, max_age_seconds=3600)
    if not tg_user:
        return JSONResponse({"ok": False, "error": "Не вдалося підтвердити Telegram-сесію. Закрийте сканер і відкрийте його знову з бота."}, status_code=401)
    operator_tg_id = int(tg_user.get("id") or 0)
    token, amp_id = _scanner_profile_token(code_text)
    if not token and not amp_id:
        return JSONResponse({"ok": False, "error": "Це не персональний QR-бейдж АМП."}, status_code=400)

    async with db.session_factory() as session:
        operator = await session.scalar(select(User).where(User.tg_id == operator_tg_id))
        if not operator or operator.status != UserStatus.ACTIVE.value or operator.role not in {
            UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value,
        }:
            return JSONResponse({"ok": False, "error": "Недостатньо прав для QR-сканера."}, status_code=403)
        await process_event_operations(session)
        event = await session.get(Event, event_id)
        if not event or event.cancelled_at or event.status in {"draft", "cancelled", "completed"}:
            return JSONResponse({"ok": False, "error": "Відмітка для цієї події недоступна."}, status_code=409)
        participant = await session.get(User, amp_id) if amp_id else await session.scalar(select(User).where(User.public_token == token))
        if not participant:
            return JSONResponse({"ok": False, "error": "Учасника за цим бейджем не знайдено."}, status_code=404)

        result = await admin_scan_event_participant(session, event.id, participant.id, operator, allow_register=False)
        state = str(result.get("code") or "")
        reg = result.get("registration")
        status_registered = state not in {"unregistered", "user_not_found", "user_inactive"}
        status_attended = state in {"confirmed", "already_attended"}

        if state == "unregistered":
            receipt = (
                f"📷 <b>Бейдж відскановано</b>\n\n"
                f"👤 <b>{participant.full_name}</b>\n"
                f"🪪 АМП-{participant.id:04d}\n"
                f"📅 Подія: <b>{event.title}</b>\n\n"
                f"🔴 Зареєстрований: <b>ні</b>\n"
                f"⚪ Відмічений на події: <b>ні</b>\n\n"
                "Натисніть кнопку нижче, щоб зареєструвати та підтвердити присутність."
            )
            await queue_telegram_delivery(
                session, operator.tg_id, receipt,
                source="telegram_miniapp_scanner",
                dedupe_key=f"miniapp_scan:{event.id}:{operator.id}:{scan_id}" if scan_id else None,
                button_text="✅ Зареєструвати та підтвердити",
                callback_data=f"admin:event_scanner_confirm:{event.id}:{participant.id}",
            )
            await session.commit()
            return JSONResponse({
                "ok": True, "state": "unregistered", "name": participant.full_name,
                "amp_id": f"АМП-{participant.id:04d}", "event": event.title,
                "registered": False, "attended": False,
                "message": "Учасник не зареєстрований. У чат надіслано кнопку підтвердження.",
            })

        if not result.get("ok"):
            receipt = (
                f"📷 <b>Бейдж відскановано</b>\n\n"
                f"👤 <b>{participant.full_name}</b>\n🪪 АМП-{participant.id:04d}\n"
                f"📅 Подія: <b>{event.title}</b>\n\n❌ {result.get('message', 'Не вдалося підтвердити участь.')}"
            )
            await queue_telegram_delivery(
                session, operator.tg_id, receipt, source="telegram_miniapp_scanner",
                dedupe_key=f"miniapp_scan:{event.id}:{operator.id}:{scan_id}" if scan_id else None,
            )
            await session.commit()
            return JSONResponse({"ok": False, "error": result.get("message", "Не вдалося обробити бейдж."), "name": participant.full_name}, status_code=409)

        if state == "confirmed":
            await log_audit(session, "telegram_miniapp_qr_scanner_attendance", operator, entity_type="event", entity_id=event.id, details=f"АМП-{participant.id:04d}")
            participant_notice = f"✅ Участь у події «{event.title}» підтверджено.\n+{event.xp_reward} XP"
            if event.volunteer_hours:
                participant_notice += f"\n+{event.volunteer_hours:g} волонтерських годин"
            await queue_telegram_delivery(
                session, participant.tg_id, participant_notice,
                source="telegram_event_scanner",
                dedupe_key=f"telegram_event_scanner:{event.id}:{reg.id}" if reg else f"telegram_event_scanner:{event.id}:{participant.id}",
            )

        receipt = (
            f"📷 <b>Бейдж відскановано</b>\n\n"
            f"👤 <b>{participant.full_name}</b>\n"
            f"🪪 АМП-{participant.id:04d}\n"
            f"📅 Подія: <b>{event.title}</b>\n\n"
            f"🟢 Зареєстрований: <b>{'так' if status_registered else 'ні'}</b>\n"
            f"✅ Відмічений на події: <b>{'так' if status_attended else 'ні'}</b>\n"
            + ("ℹ️ Присутність уже була підтверджена раніше." if state == "already_attended" else "🎉 Присутність підтверджено.")
        )
        await queue_telegram_delivery(
            session, operator.tg_id, receipt,
            source="telegram_miniapp_scanner",
            dedupe_key=f"miniapp_scan:{event.id}:{operator.id}:{scan_id}" if scan_id else None,
        )
        await session.commit()
        return JSONResponse({
            "ok": True, "state": state, "name": participant.full_name,
            "amp_id": f"АМП-{participant.id:04d}", "event": event.title,
            "registered": status_registered, "attended": status_attended,
            "message": "Присутність уже підтверджена." if state == "already_attended" else "Присутність підтверджено.",
        })


@router.get("/event/{share_token}", response_class=HTMLResponse)
async def public_event_page(request: Request, share_token: str):
    """Public, data-minimized event card used for sharing and registration links."""
    async with db.session_factory() as session:
        event = await session.scalar(select(Event).where(Event.share_token == share_token))
        if not event or event.status == "draft":
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        registered = int(await session.scalar(select(func.count(EventRegistration.id)).where(
            EventRegistration.event_id == event.id,
            EventRegistration.status.in_(["registered", "reserved", "checked_in", "attended"]),
        )) or 0)
    return templates.TemplateResponse(
        request=request, name="event_public.html",
        context={"request": request, "event": event, "registered": registered, "share_url": f"{settings.public_base_url}/event/{event.share_token}"},
    )


@router.get("/event/{share_token}/register")
async def public_event_register_redirect(share_token: str):
    async with db.session_factory() as session:
        event = await session.scalar(select(Event).where(Event.share_token == share_token))
        if not event or event.status == "draft":
            raise HTTPException(status_code=404, detail="Подію не знайдено")
    if not settings.bot_token:
        raise HTTPException(status_code=503, detail="Telegram-бот тимчасово недоступний")
    from aiogram import Bot
    bot = Bot(settings.bot_token)
    try:
        me = await bot.get_me()
    finally:
        await bot.session.close()
    return RedirectResponse(f"https://t.me/{me.username}?start=event_{share_token}", status_code=302)

@router.get("/admin/events", response_class=HTMLResponse)
async def events(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "newest"):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        stmt = select(Event)
        if q: stmt = stmt.where(or_(Event.title.ilike(f"%{q}%"), Event.location.ilike(f"%{q}%"), Event.description.ilike(f"%{q}%")))
        if status: stmt = stmt.where(Event.status == status)
        now_utc = clock.now_utc()
        now = clock.local_wall(now_utc)
        if type == "upcoming": stmt = stmt.where(Event.starts_at >= now)
        elif type == "past": stmt = stmt.where(Event.starts_at < now)
        cutoff_map = {"7d": 7, "30d": 30, "90d": 90}
        if period in cutoff_map:
            before = clock.local_wall(now_utc - timedelta(days=cutoff_map[period]))
            after = clock.local_wall(now_utc + timedelta(days=cutoff_map[period]))
            stmt = stmt.where(Event.starts_at >= before, Event.starts_at <= after)
        order_map = {"oldest": Event.starts_at.asc(), "title": Event.title.asc(), "newest": Event.starts_at.desc()}
        rows=(await session.scalars(stmt.order_by(order_map.get(sort, Event.starts_at.desc())).limit(250))).all()
        view_stats = await content_view_stats(session, "event", [row.id for row in rows])
        return templates.TemplateResponse(request=request,name="events.html",context=ctx(request,rows=rows,view_stats=view_stats,today=clock.today_local(),q=q,status=status,period=period,type=type,sort=sort))


@router.get("/admin/events/{event_id}", response_class=HTMLResponse)
async def event_detail(request: Request, event_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        event = await session.get(Event, event_id)
        if not event:
            return HTMLResponse("Подію не знайдено", status_code=404)
        registrations = (await session.execute(
            select(EventRegistration, User)
            .join(User, User.id == EventRegistration.user_id)
            .where(EventRegistration.event_id == event.id)
            .order_by(EventRegistration.registered_at.asc())
        )).all()
        counts = {
            "roster": len(registrations),
            "registered": sum(1 for reg, _ in registrations if reg.status == "registered"),
            "reserved": sum(1 for reg, _ in registrations if reg.status == "reserved"),
            "all": sum(1 for reg, _ in registrations if reg.status in {"registered", "reserved", "checked_in", "attended"}),
            "waitlisted": sum(1 for reg, _ in registrations if reg.status == "waitlisted"),
            "checked_in": sum(1 for reg, _ in registrations if reg.status == "checked_in"),
            "cancelled": sum(1 for reg, _ in registrations if reg.status == "cancelled"),
            "present": sum(1 for reg, _ in registrations if reg.status in {"checked_in", "attended"}),
            "confirmed": sum(1 for reg, _ in registrations if reg.status == "attended"),
            "no_show": sum(1 for reg, _ in registrations if reg.status == "no_show"),
        }
        all_feedback_rows = list((await session.scalars(
            select(EventFeedback).where(EventFeedback.event_id == event.id)
        )).all())
        feedback_rows = [row for row in all_feedback_rows if row.status == "completed"]
        feedback_invited = sum(1 for row in all_feedback_rows if row.prompted_at is not None)
        def pct(field):
            values=[getattr(row,field) for row in feedback_rows if getattr(row,field) is not None]
            return round(sum(1 for value in values if value) * 100 / len(values)) if values else 0
        ratings=[int(row.rating) for row in feedback_rows if row.rating is not None]
        feedback_stats = {
            "responses": len(feedback_rows),
            "invited": feedback_invited,
            "response_rate": round(len(feedback_rows) * 100 / feedback_invited, 1) if feedback_invited else 0.0,
            "avg_rating": round(sum(ratings)/len(ratings), 1) if ratings else 0,
            "useful": pct("useful"),
            "new_knowledge": pct("new_knowledge"),
            "felt_safe": pct("felt_safe"),
            "would_return": pct("would_return"),
        }
        attendance_window = await event_checkin_window(session, event)

        xp_rows = list((await session.scalars(
            select(XPTransaction).where(
                XPTransaction.event_id == event.id,
                XPTransaction.category == "event",
                XPTransaction.amount > 0,
            )
        )).all())
        xp_by_user = {}
        for row in xp_rows:
            xp_by_user[row.user_id] = xp_by_user.get(row.user_id, 0) + int(row.amount or 0)
        feedback_by_user = {row.user_id: row for row in all_feedback_rows}
        counts["xp_awarded"] = len(xp_by_user)
        counts["feedback_completed"] = len(feedback_rows)

        scanner_actions = {"web_event_qr_scanner_attendance", "telegram_miniapp_qr_scanner_attendance"}
        last_scanner_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "event",
                AuditLog.entity_id == event.id,
                AuditLog.action.in_(scanner_actions),
            ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1)
        )
        scanner_status = {
            "available": bool(not event.cancelled_at and event.status not in {"cancelled", "draft", "completed"}),
            "window_state": attendance_window["state"],
            "last_scan_at": last_scanner_audit.created_at if last_scanner_audit else None,
            "last_scan_actor": last_scanner_audit.actor_label if last_scanner_audit else "",
        }
        view_stat = await content_view_stat(session, "event", event.id)
        operation_funnel = [
            {"key": "registered", "label": "Зареєстровані", "value": counts["registered"] + counts["reserved"] + counts["checked_in"] + counts["confirmed"] + counts["no_show"]},
            {"key": "waitlist", "label": "Черга / резерв", "value": counts["waitlisted"] + counts["reserved"]},
            {"key": "checkin", "label": "Відмітка", "value": counts["checked_in"] + counts["confirmed"]},
            {"key": "attended", "label": "Підтверджено", "value": counts["confirmed"]},
            {"key": "xp", "label": "XP нараховано", "value": counts["xp_awarded"]},
            {"key": "feedback", "label": "Відгук", "value": counts["feedback_completed"]},
        ]
        return templates.TemplateResponse(
            request=request, name="event_detail.html",
            context=ctx(
                request, event=event, registrations=registrations, counts=counts, feedback_stats=feedback_stats, attendance_window=attendance_window,
                xp_by_user=xp_by_user, feedback_by_user=feedback_by_user, scanner_status=scanner_status, operation_funnel=operation_funnel, view_stat=view_stat,
                share_url=f"{settings.public_base_url}/event/{event.share_token}" if event.share_token else "",
            )
        )


@router.get("/admin/events/{event_id}/participants.xlsx")
async def event_participants_xlsx(request: Request, event_id: int):
    """Data-minimized event register available to any authenticated web admin."""
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        registrations = (await session.execute(
            select(EventRegistration, User)
            .join(User, User.id == EventRegistration.user_id)
            .where(EventRegistration.event_id == event.id)
            .order_by(User.full_name.asc(), EventRegistration.registered_at.asc())
        )).all()
        data = export_event_participants_excel(event, list(registrations), include_sensitive=False)
        await log_audit(
            session,
            "web_event_participants_export_basic",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="event",
            entity_id=event.id,
            details=f"Завантажено базовий список учасників події «{event.title}» ({len(registrations)} записів)",
        )
        await session.commit()

    safe_title = "".join(ch for ch in event.title if ch.isalnum() or ch in " _-").strip()[:60] or f"event_{event.id}"
    ua_filename = f"{safe_title}_учасники_{event.starts_at.strftime('%Y-%m-%d')}.xlsx"
    ascii_filename = f"event_{event.id}_participants_{event.starts_at.strftime('%Y-%m-%d')}.xlsx"
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(ua_filename)}"},
    )


@router.get("/admin/events/{event_id}/participants.pdf")
async def event_participants_pdf(request: Request, event_id: int):
    """Print-friendly minimized PDF register for an event."""
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        registrations = (await session.execute(
            select(EventRegistration, User)
            .join(User, User.id == EventRegistration.user_id)
            .where(EventRegistration.event_id == event.id)
            .order_by(User.full_name.asc(), EventRegistration.registered_at.asc())
        )).all()
        data = export_event_participants_pdf(event, list(registrations), include_sensitive=False)
        await log_audit(session, "web_event_participants_export_basic", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id, details=f"Завантажено базовий PDF списку учасників події «{event.title}» ({len(registrations)} записів)")
        await session.commit()
    safe_title = "".join(ch for ch in event.title if ch.isalnum() or ch in " _-").strip()[:60] or f"event_{event.id}"
    ua_filename = f"{safe_title}_учасники_{event.starts_at.strftime('%Y-%m-%d')}.pdf"
    ascii_filename = f"event_{event.id}_participants_{event.starts_at.strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(BytesIO(data), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(ua_filename)}"})


@router.get("/admin/events/{event_id}/participants-sensitive.xlsx")
async def event_participants_sensitive_xlsx(request: Request, event_id: int):
    """Expanded event register with sensitive fields; superadmin only."""
    if r := guard_permission(request, "reports.sensitive_export"):
        return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        registrations = (await session.execute(
            select(EventRegistration, User)
            .join(User, User.id == EventRegistration.user_id)
            .where(EventRegistration.event_id == event.id)
            .order_by(User.full_name.asc(), EventRegistration.registered_at.asc())
        )).all()
        data = export_event_participants_excel(event, list(registrations), include_sensitive=True)
        await log_audit(
            session,
            "web_event_participants_export_sensitive",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="event",
            entity_id=event.id,
            details=f"Завантажено розширений список із персональними даними події «{event.title}» ({len(registrations)} записів)",
        )
        await session.commit()

    safe_title = "".join(ch for ch in event.title if ch.isalnum() or ch in " _-").strip()[:60] or f"event_{event.id}"
    ua_filename = f"{safe_title}_РОЗШИРЕНИЙ_{event.starts_at.strftime('%Y-%m-%d')}.xlsx"
    ascii_filename = f"event_{event.id}_participants_sensitive_{event.starts_at.strftime('%Y-%m-%d')}.xlsx"
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(ua_filename)}"},
    )


@router.get("/admin/events/{event_id}/participants-sensitive.pdf")
async def event_participants_sensitive_pdf(request: Request, event_id: int):
    """Expanded print-friendly PDF register; superadmin only."""
    if r := guard_permission(request, "reports.sensitive_export"):
        return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        registrations = (await session.execute(
            select(EventRegistration, User)
            .join(User, User.id == EventRegistration.user_id)
            .where(EventRegistration.event_id == event.id)
            .order_by(User.full_name.asc(), EventRegistration.registered_at.asc())
        )).all()
        data = export_event_participants_pdf(event, list(registrations), include_sensitive=True)
        await log_audit(session, "web_event_participants_export_sensitive", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id, details=f"Завантажено розширений PDF із персональними даними події «{event.title}» ({len(registrations)} записів)")
        await session.commit()
    safe_title = "".join(ch for ch in event.title if ch.isalnum() or ch in " _-").strip()[:60] or f"event_{event.id}"
    ua_filename = f"{safe_title}_РОЗШИРЕНИЙ_{event.starts_at.strftime('%Y-%m-%d')}.pdf"
    ascii_filename = f"event_{event.id}_participants_sensitive_{event.starts_at.strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(BytesIO(data), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(ua_filename)}"})


@router.post("/admin/events/{event_id}/registration-template")
async def upload_event_registration_template(request: Request, event_id: int, template_file: UploadFile = File(...)):
    if r := guard(request): return r
    filename = (template_file.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".docx"}:
        raise HTTPException(status_code=400, detail="Підтримуються лише шаблони Word .docx або Excel .xlsx")
    raw = await template_file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Файл порожній")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл завеликий. Максимум 20 МБ")
    ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if suffix == ".docx" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    path = await store_file_bytes(db, raw, "event_registration_templates", original_name=filename, content_type=ctype)
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            await delete_image(path)
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        old_path = event.registration_template_path
        event.registration_template_path = path
        event.registration_template_name = filename
        event.registration_template_type = suffix.lstrip(".")
        await log_audit(session, "web_event_registration_template_upload", actor_label=request.session.get("admin_name","web"), entity_type="event", entity_id=event.id, details=filename)
        await session.commit()
    if old_path and old_path != path:
        await delete_image(old_path)
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/registration-template/remove")
async def remove_event_registration_template(request: Request, event_id: int):
    if r := guard(request): return r
    old_path = None
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        old_path = event.registration_template_path
        old_name = event.registration_template_name or ""
        event.registration_template_path = None
        event.registration_template_name = None
        event.registration_template_type = None
        await log_audit(session, "web_event_registration_template_remove", actor_label=request.session.get("admin_name","web"), entity_type="event", entity_id=event.id, details=old_name)
        await session.commit()
    if old_path:
        await delete_image(old_path)
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.get("/admin/events/{event_id}/registration-form")
async def download_event_registration_form(request: Request, event_id: int):
    """Fill donor DOCX/XLSX without changing its layout; fall back to AMP XLSX."""
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        registrations = list((await session.execute(
            select(EventRegistration, User).join(User, User.id == EventRegistration.user_id)
            .where(EventRegistration.event_id == event.id, EventRegistration.status != "cancelled")
            .order_by(User.full_name.asc(), EventRegistration.registered_at.asc())
        )).all())
        include_sensitive = has_web_permission(request, "reports.sensitive_export")
        if event.registration_template_path and event.registration_template_name:
            raw = await load_file_bytes(db, event.registration_template_path)
            if not raw:
                raise HTTPException(status_code=404, detail="Завантажений шаблон не знайдено")
            try:
                data, media_type, extension = fill_registration_template(
                    raw, event.registration_template_name, event, registrations, include_sensitive=include_sensitive
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            base = Path(event.registration_template_name).stem[:80] or f"event_{event.id}"
            ua_filename = f"{base}_заповнений{extension}"
            ascii_filename = f"event_{event.id}_donor_register{extension}"
            action = "web_event_donor_register_export_sensitive" if include_sensitive else "web_event_donor_register_export_basic"
        else:
            data = export_event_participants_excel(event, registrations, include_sensitive=include_sensitive)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            extension = ".xlsx"
            ua_filename = f"АМПасадори_{event.title[:55]}_реєстраційний_список.xlsx"
            ascii_filename = f"event_{event.id}_amp_register.xlsx"
            action = "web_event_standard_register_export_sensitive" if include_sensitive else "web_event_standard_register_export_basic"
        await log_audit(session, action, actor_label=request.session.get("admin_name","web"), entity_type="event", entity_id=event.id, details=f"records={len(registrations)}; template={event.registration_template_name or 'AMP standard'}")
        await session.commit()
    return StreamingResponse(
        BytesIO(data), media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(ua_filename)}"},
    )


@router.get("/admin/events/{event_id}/checkin-qr.png")
async def event_checkin_qr(request: Request, event_id: int, download: int = 0):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
    if not settings.bot_token:
        raise HTTPException(status_code=500, detail="Не налаштовано токен Telegram-бота")
    from aiogram import Bot
    bot = Bot(settings.bot_token)
    try:
        me = await bot.get_me()
    finally:
        await bot.session.close()
    deep_link = f"https://t.me/{me.username}?start=checkin_{event.checkin_token}"
    qr = qrcode.QRCode(version=None, box_size=12, border=3)
    qr.add_data(deep_link); qr.make(fit=True)
    img = qr.make_image(fill_color="#0B5B6C", back_color="white").convert("RGB")
    bio = BytesIO(); img.save(bio, format="PNG"); bio.seek(0)
    disposition = "attachment" if download else "inline"
    safe_name = f"AMP_event_{event_id}_QR.png"
    return StreamingResponse(
        bio, media_type="image/png",
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'}
    )


async def _scanner_actor_user(session, request: Request) -> User | None:
    """Best-effort mapping of the signed web staff account to an AMP staff profile."""
    account_id = int(request.session.get("admin_account_id") or 0)
    if account_id:
        account = await session.get(WebStaffAccount, account_id)
        if account and account.two_factor_tg_id:
            mapped = await session.scalar(select(User).where(
                User.tg_id == account.two_factor_tg_id,
                User.role.in_([UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value]),
            ))
            if mapped:
                return mapped
    return await session.scalar(
        select(User).where(User.role.in_([UserRole.SUPERADMIN.value, UserRole.ADMIN.value, UserRole.COORDINATOR.value]))
        .order_by(User.id.asc())
    )


def _scanner_profile_token(raw: str) -> tuple[str | None, int | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    amp = re.fullmatch(r"(?:AMP|АМП)-(\d{1,9})", text, flags=re.I)
    if amp:
        return None, int(amp.group(1))
    if text.startswith("profile_"):
        return text.removeprefix("profile_"), None
    try:
        parsed = urlparse(text)
        start = (parse_qs(parsed.query).get("start") or [""])[0]
        if start.startswith("profile_"):
            return start.removeprefix("profile_"), None
    except (TypeError, ValueError) as exc:
        logging.getLogger("amp.web.events").debug(
            "Не вдалося розібрати scanner URL",
            extra=log_extra("WEB_SCANNER_URL_PARSE_FAILED", input_length=len(text), exception_type=type(exc).__name__),
        )
    match = re.search(r"(?:start=|/)profile_([A-Za-z0-9_-]{8,80})", text)
    if match:
        return match.group(1), None
    # A raw public token is accepted as a scanner fallback.
    if re.fullmatch(r"[A-Za-z0-9_-]{8,80}", text):
        return text, None
    return None, None


@router.get("/admin/events/{event_id}/scanner/telegram")
async def event_scanner_telegram(request: Request, event_id: int):
    """Open the event scanner in Telegram; works independently of browser QR APIs."""
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event or event.status not in {"open", "closed", "postponed"}:
            return HTMLResponse("QR-сканер для цієї події недоступний", status_code=409)
    if not settings.bot_token:
        return HTMLResponse("BOT_TOKEN не налаштований", status_code=503)
    bot = Bot(settings.bot_token)
    try:
        me = await bot.get_me()
    finally:
        await bot.session.close()
    return RedirectResponse(f"https://t.me/{me.username}?start=adminscan_{event.checkin_token}", status_code=302)


@router.post("/admin/events/{event_id}/scanner")
async def event_web_scanner(
    request: Request, event_id: int, code: str = Form(...), action: str = Form("scan")
):
    if r := guard(request):
        return r
    action = action if action in {"scan", "register_confirm"} else "scan"
    token, amp_id = _scanner_profile_token(code)
    if not token and not amp_id:
        return JSONResponse({"ok": False, "error": "QR не розпізнано. Скануйте персональний QR-бейдж учасника."}, status_code=400)

    async with db.session_factory() as session:
        await process_event_operations(session)
        event = await session.get(Event, event_id)
        if not event or event.cancelled_at or event.status in {"draft", "cancelled", "completed"}:
            return JSONResponse({"ok": False, "error": "Відмітка для цієї події недоступна."}, status_code=409)
        attendance_window = await event_checkin_window(session, event)
        if attendance_window["state"] != "open":
            message = "Відмітку ще не відкрито." if attendance_window["state"] == "too_early" else "Вікно відмітки та підтвердження участі вже закрито. Використайте ручне підтвердження з причиною."
            return JSONResponse({"ok": False, "error": message, "state": attendance_window["state"]}, status_code=409)
        user = await session.get(User, amp_id) if amp_id else await session.scalar(select(User).where(User.public_token == token))
        if not user:
            return JSONResponse({"ok": False, "error": "Учасника за цим QR не знайдено."}, status_code=404)
        if user.status != UserStatus.ACTIVE.value:
            return JSONResponse({"ok": False, "error": f"Акаунт учасника не активний: {label(user.status)}.", "name": user.full_name, "amp_id": f"АМП-{user.id:04d}"}, status_code=409)

        reg = await session.scalar(select(EventRegistration).where(
            EventRegistration.event_id == event.id, EventRegistration.user_id == user.id
        ))
        if reg and reg.status == "attended":
            return JSONResponse({
                "ok": True, "state": "already_attended", "name": user.full_name,
                "amp_id": f"АМП-{user.id:04d}", "registration": "Був присутній",
                "message": "Присутність уже була підтверджена раніше.",
            })

        eligible = bool(reg and reg.status in {"registered", "reserved", "checked_in"})
        if not eligible and action != "register_confirm":
            return JSONResponse({
                "ok": True, "state": "unregistered", "requires_registration": True,
                "name": user.full_name, "amp_id": f"АМП-{user.id:04d}",
                "registration": event_registration_status_label(reg.status) if reg else "Не зареєстрований",
                "message": "Учасник не зареєстрований на цю подію.",
            })

        now = clock.storage_utc()
        if not reg:
            reg = EventRegistration(event_id=event.id, user_id=user.id, status="registered", registered_at=now)
            session.add(reg)
            await session.flush()
        elif action == "register_confirm" and reg.status not in {"registered", "reserved", "checked_in"}:
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

        actor = await _scanner_actor_user(session, request)
        if not actor:
            return JSONResponse({"ok": False, "error": "Не знайдено службовий профіль для підтвердження участі."}, status_code=409)
        result = await confirm_single_event_attendance(session, event, reg, actor)
        if not result:
            return JSONResponse({"ok": False, "error": "Не вдалося підтвердити присутність."}, status_code=409)
        confirmed_user, total, level_name, leveled = result
        await log_audit(
            session, "web_event_qr_scanner_attendance", actor_label=request.session.get("admin_name", "web"),
            entity_type="event", entity_id=event.id, details=f"АМП-{user.id:04d}; scanner; register_confirm={action == 'register_confirm'}",
        )
        notice = f"✅ Участь у події «{event.title}» підтверджено.\n+{event.xp_reward} XP"
        if event.volunteer_hours:
            notice += f"\n+{event.volunteer_hours:g} волонтерських годин"
        notice += f"\nВсього: {total} XP"
        if leveled:
            notice += f"\n🎉 Новий рівень: {level_name}"
        await queue_telegram_delivery(
            session, confirmed_user.tg_id, notice, source="event_scanner",
            dedupe_key=f"event_scanner_attendance:{event.id}:{reg.id}",
        )
        await session.commit()
        return JSONResponse({
            "ok": True, "state": "confirmed", "name": user.full_name,
            "amp_id": f"АМП-{user.id:04d}", "registration": "Зареєстрований",
            "message": "Присутність підтверджено", "xp": event.xp_reward,
        })


@router.post("/admin/events/{event_id}/registrations/{registration_id}/mark-present")
async def web_mark_present(request: Request, event_id: int, registration_id: int, override_reason: str = Form("")):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        reg = await session.get(EventRegistration, registration_id)
        if event and event.status != "cancelled" and not event.cancelled_at and reg and reg.event_id == event.id and reg.status in {"registered", "reserved"}:
            window = await event_checkin_window(session, event)
            reason = override_reason.strip()
            if window["state"] != "open" and len(reason) < 5:
                raise HTTPException(status_code=409, detail="Поза check-in window потрібна причина ручного override (мінімум 5 символів).")
            reg.status = "checked_in"
            reg.checkin_at = clock.storage_utc()
            reg.reservation_expires_at = None
            if window["state"] != "open":
                await log_audit(session, "web_event_attendance_override", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id, details=f"Реєстрація #{reg.id}; mark-present; window={window['state']}; reason={reason}")
            await log_audit(
                session, "web_event_mark_present", actor_label=request.session.get("admin_name", "web"),
                entity_type="event", entity_id=event.id, details=f"Реєстрація #{reg.id}: вручну відмічено присутність"
            )
            await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/registrations/{registration_id}/confirm")
async def web_confirm_single_attendance(request: Request, event_id: int, registration_id: int, override_reason: str = Form("")):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        reg = await session.get(EventRegistration, registration_id)
        admin_user = await session.scalar(
            select(User).where(User.role.in_([UserRole.SUPERADMIN.value, UserRole.ADMIN.value])).order_by(User.id.asc())
        )
        if event and event.status != "cancelled" and not event.cancelled_at and reg and admin_user and reg.event_id == event.id:
            window = await event_checkin_window(session, event)
            reason = override_reason.strip()
            if window["state"] != "open" and len(reason) < 5:
                raise HTTPException(status_code=409, detail="Поза вікном відмітки та підтвердження участі потрібна причина ручного підтвердження (мінімум 5 символів).")
            result = await confirm_single_event_attendance(session, event, reg, admin_user, override_reason=reason or None)
            if result:
                user, total, level_name, leveled = result
                text = f"✅ Участь у події «{event.title}» підтверджено.\n+{event.xp_reward} XP"
                if event.volunteer_hours:
                    text += f"\n+{event.volunteer_hours:g} волонтерських годин"
                text += f"\nВсього: {total} XP"
                if leveled:
                    text += f"\n🎉 Новий рівень: {level_name}"
                await queue_telegram_delivery(
                    session, user.tg_id, text, source="event_attendance",
                    notification_type="event", title=f"Участь: {event.title}",
                    recipient_user_id=user.id, entity_type="event_registration", entity_id=reg.id,
                    dedupe_key=f"web_event_attendance:{event.id}:{reg.id}",
                )
                if window["state"] != "open":
                    await log_audit(session, "web_event_attendance_override", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id, details=f"Реєстрація #{reg.id}; confirm; window={window['state']}; reason={reason}")
                await log_audit(
                    session, "web_event_attendance_single",
                    actor_label=request.session.get("admin_name", "web"),
                    entity_type="event", entity_id=event.id,
                    details=f"Підтверджено участь користувача АМП-{user.id:04d}"
                )
                await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/registrations/{registration_id}/cancel")
async def web_cancel_event_registration(request: Request, event_id: int, registration_id: int, admin_note: str = Form("")):
    if r := guard(request): return r
    notify_id = None
    notify_text = ""
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        reg = await session.get(EventRegistration, registration_id)
        if not event or not reg or reg.event_id != event.id:
            raise HTTPException(status_code=404, detail="Реєстрацію не знайдено")
        if reg.status not in {"registered", "reserved", "waitlisted", "checked_in"}:
            raise HTTPException(status_code=409, detail="Цю участь уже не можна скасувати")
        user = await session.get(User, reg.user_id)
        reg.status = "cancelled"
        reg.checkin_at = None
        reg.reservation_expires_at = None
        await process_event_operations(session)
        if user:
            notify_id = user.tg_id
            notify_text = f"ℹ️ Вашу реєстрацію на подію <b>{event.title}</b> скасовано адміністратором." + (f"\n💬 {admin_note.strip()}" if admin_note.strip() else "")
        await log_audit(session, "web_event_registration_cancelled", actor_label=request.session.get("admin_name","web"), entity_type="event", entity_id=event.id, details=f"Реєстрація #{reg.id}; {user.full_name if user else reg.user_id}; {admin_note.strip()}")
        await session.commit()
    if notify_id:
        await notify_telegram(notify_id, notify_text)
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/registrations/{registration_id}/no-show")
async def web_mark_no_show(request: Request, event_id: int, registration_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        reg = await session.get(EventRegistration, registration_id)
        if not event or not reg or reg.event_id != event.id:
            raise HTTPException(status_code=404, detail="Реєстрацію не знайдено")
        if reg.status not in {"registered", "reserved"}:
            raise HTTPException(status_code=409, detail="Статус цієї участі не можна змінити на «Не прийшов»")
        reg.status = "no_show"
        reg.no_show_at = clock.storage_utc()
        reg.reservation_expires_at = None
        await log_audit(session, "web_event_no_show", actor_label=request.session.get("admin_name","web"), entity_type="event", entity_id=event.id, details=f"АМП-{reg.user_id:04d}")
        await process_event_operations(session)
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/registrations/{registration_id}/delete")
async def web_delete_cancelled_registration(request: Request, event_id: int, registration_id: int):
    """Delete only a cancelled event registration from the event roster."""
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        reg = await session.get(EventRegistration, registration_id)
        if not event or not reg or reg.event_id != event.id:
            raise HTTPException(status_code=404, detail="Реєстрацію не знайдено")
        if reg.status != "cancelled":
            raise HTTPException(status_code=409, detail="Видаляти можна лише скасовані реєстрації")
        user = await session.get(User, reg.user_id)
        user_label = f"АМП-{reg.user_id:04d}"
        if user and user.full_name:
            user_label = f"{user.full_name} ({user_label})"
        await log_audit(
            session,
            "web_event_registration_deleted",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="event",
            entity_id=event.id,
            details=f"Видалено скасовану реєстрацію учасника {user_label} з події «{event.title}»",
        )
        await session.delete(reg)
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/confirm-attendance")
async def web_confirm_attendance(request: Request, event_id: int, override_reason: str = Form("")):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        admin_user = await session.scalar(
            select(User).where(User.role.in_([UserRole.SUPERADMIN.value, UserRole.ADMIN.value])).order_by(User.id.asc())
        )
        if not event or not admin_user or event.status == "cancelled" or event.cancelled_at:
            return RedirectResponse(f"/admin/events/{event_id}", 303)
        window = await event_checkin_window(session, event)
        reason = override_reason.strip()
        if window["state"] != "open" and len(reason) < 5:
            raise HTTPException(status_code=409, detail="Поза вікном відмітки та підтвердження участі потрібна причина ручного підтвердження (мінімум 5 символів).")
        count, results = await confirm_event_attendance(session, event, admin_user, override_reason=reason or None)
        for user, total, level_name, leveled in results:
            text = f"✅ Участь у події «{event.title}» підтверджено.\n+{event.xp_reward} XP"
            if event.volunteer_hours:
                text += f"\n+{event.volunteer_hours:g} волонтерських годин"
            text += f"\nВсього: {total} XP"
            if leveled:
                text += f"\n🎉 Новий рівень: {level_name}"
            reg = await session.scalar(select(EventRegistration).where(EventRegistration.event_id == event.id, EventRegistration.user_id == user.id))
            await queue_telegram_delivery(
                session, user.tg_id, text, source="event_attendance",
                notification_type="event", title=f"Участь: {event.title}",
                recipient_user_id=user.id, entity_type="event_registration", entity_id=(reg.id if reg else None),
                dedupe_key=f"web_event_attendance:{event.id}:{user.id}",
            )
        if window["state"] != "open":
            await log_audit(session, "web_event_attendance_override", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id, details=f"bulk confirm; count={count}; window={window['state']}; reason={reason}")
        await log_audit(session, "web_event_attendance", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id, details=f"Підтверджено присутніх: {count}")
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}", 303)


@router.post("/admin/events/{event_id}/operations/refresh-queue")
async def event_operations_refresh_queue(request: Request, event_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        changed = await process_event_operations(session, event_id=event.id)
        await log_audit(
            session, "web_event_operations_refresh_queue",
            actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id,
            details=f"Оновлено чергу події; зміни={changed}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}#event-operations", 303)


@router.post("/admin/events/{event_id}/operations/mark-no-show")
async def event_operations_mark_no_show(request: Request, event_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
        window = await event_checkin_window(session, event)
        if window["state"] != "closed":
            raise HTTPException(status_code=409, detail="Масове позначення «Не прийшов» доступне лише після закриття вікна відмітки.")
        rows = list((await session.scalars(
            select(EventRegistration).where(
                EventRegistration.event_id == event.id,
                EventRegistration.status.in_(["registered", "reserved"]),
            )
        )).all())
        now = clock.storage_utc()
        for reg in rows:
            reg.status = "no_show"
            reg.no_show_at = now
            reg.reservation_expires_at = None
        await log_audit(
            session, "web_event_operations_bulk_no_show",
            actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id,
            details=f"Масово позначено «Не прийшов»: {len(rows)}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}#event-operations", 303)


@router.post("/admin/events/create")
async def event_create(
    request: Request, title: str = Form(...), day: int = Form(...), month: int = Form(...), year: int = Form(...),
    event_time: str = Form(...), location: str = Form("АМП"), description: str = Form(""), xp_reward: int = Form(10),
    volunteer_hours: float = Form(0), capacity: str = Form(""), status: str = Form("open"), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    starts_at = compose_event_datetime(day, month, year, event_time)
    image = await save_image(photo, "events")
    campaign_id=None
    async with db.session_factory() as session:
        xp_reward = normalize_event_xp(xp_reward)
        e = Event(
            title=title.strip(), description=description.strip(), starts_at=starts_at, location=location.strip() or "АМП",
            xp_reward=xp_reward, volunteer_hours=max(0, volunteer_hours), capacity=opt_int(capacity), status=status if status in {"draft", "open", "closed"} else "open",
            checkin_token=token_urlsafe(18), share_token=token_urlsafe(18), image_path=image,
        )
        session.add(e)
        await session.flush()
        await log_audit(session, "web_event_create", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=e.id, details=e.title)
        if e.status=="open":
            users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
            text=f"📅 <b>Нова подія в АМП</b>\n\n<b>{e.title}</b>\n🕒 {e.starts_at.strftime('%d.%m.%Y %H:%M')}\n📍 {e.location}\n⚡ {e.xp_reward} XP\n\nВідкрий у боті розділ «📅 Події», щоб переглянути деталі та зареєструватися."
            campaign_id=await _queue_system_broadcast(session,users,text,author_label=request.session.get("admin_name","web"),audience_label=f"Нова подія: {e.title}",template_code="event_created")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/events", 303)


@router.post("/admin/events/{event_id}/update")
async def event_update(
    request: Request, event_id: int, title: str = Form(...), day: int = Form(...), month: int = Form(...), year: int = Form(...),
    event_time: str = Form(...), location: str = Form("АМП"), description: str = Form(""), xp_reward: int = Form(10),
    volunteer_hours: float = Form(0), capacity: str = Form(""), status: str = Form("open"),
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
            e.xp_reward = normalize_event_xp(xp_reward); e.volunteer_hours = max(0, volunteer_hours); e.capacity = opt_int(capacity)
            if not e.cancelled_at and e.status not in {"postponed", "completed", "cancelled"} and status in {"draft", "open", "closed"}:
                e.status = status
            if remove_image:
                await delete_image(e.image_path); e.image_path = None
            img = await save_image(photo, "events")
            if img:
                await delete_image(e.image_path); e.image_path = img
            await log_audit(session, "web_event_update", actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=e.id, details=e.title)
            if not was_public and e.status=="open":
                users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
                campaign_id=await _queue_system_broadcast(session,users,f"📅 <b>Нова подія в АМП</b>\n\n<b>{e.title}</b>\n🕒 {e.starts_at.strftime('%d.%m.%Y %H:%M')}\n📍 {e.location}\n⚡ {e.xp_reward} XP\n\nВідкрий «📅 Події» у боті, щоб зареєструватися.",author_label=request.session.get("admin_name","web"),audience_label=f"Нова подія: {e.title}",template_code="event_published")
            await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/events", 303)


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

