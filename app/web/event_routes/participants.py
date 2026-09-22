from __future__ import annotations

from fastapi.responses import JSONResponse
from urllib.parse import parse_qs, urlparse
import re
from app.web.dependencies import (
    APP_VERSION, AuditLog, BytesIO, Event, EventFeedback, EventRegistration, File, Form, HTMLResponse, HTTPException, Path, RedirectResponse, Request, StreamingResponse, UploadFile, User, UserRole, UserStatus, WebStaffAccount, XPTransaction, compose_event_datetime, confirm_event_attendance, confirm_single_event_attendance, ctx, db, delete, delete_image, event_registration_status_label, export_event_participants_excel, export_event_participants_pdf, func, guard, guard_permission, has_web_permission, label, log_audit, logging, normalize_event_xp, notify_telegram, opt_int, or_, process_event_operations, qrcode, queue_telegram_delivery, quote, save_image, select, settings, store_file_bytes, templates, timedelta, token_urlsafe, update
)
from app.media import load_file_bytes
from app.telegram_webapp import validate_webapp_init_data
from app.domain_services import admin_scan_event_participant, event_checkin_window
from app.time_utils import clock
from app.observability import log_extra
from app.content_views import content_view_stat, content_view_stats
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

from .context import router


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
                from app.event_documents import fill_registration_template
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
