from __future__ import annotations

from fastapi.responses import JSONResponse
from aiogram import Bot
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

from .scanner_common import _scanner_actor_user, _scanner_profile_token

@router.get("/admin/events/{event_id}/checkin-qr.png")
async def event_checkin_qr(request: Request, event_id: int, download: int = 0):
    if r := guard(request): return r
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Подію не знайдено")
    if not settings.bot_token:
        raise HTTPException(status_code=500, detail="Не налаштовано токен Telegram-бота")
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
