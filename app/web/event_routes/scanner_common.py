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
