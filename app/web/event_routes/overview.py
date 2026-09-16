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
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

from .context import router


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
