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


@router.get("/event/{share_token}", response_class=HTMLResponse)
async def public_event_page(request: Request, share_token: str):
    """Public, data-minimized event card used for sharing and registration links."""
    async with db.session_factory() as session:
        event = await session.scalar(select(Event).where(Event.share_token == share_token))
        if not event or event.status == "draft" or getattr(event, "access_scope", "general") == "team":
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
        if not event or event.status == "draft" or getattr(event, "access_scope", "general") == "team":
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
