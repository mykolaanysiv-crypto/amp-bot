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

from .scanner_common import _scanner_actor_user, _scanner_profile_token

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
