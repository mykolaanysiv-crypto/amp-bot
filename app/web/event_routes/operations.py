from __future__ import annotations

from fastapi.responses import JSONResponse
from aiogram import Bot
from urllib.parse import parse_qs, urlparse
import re
from app.web.dependencies import (
    APP_VERSION, AuditLog, BytesIO, Event, EventFeedback, EventRegistration, File, Form, HTMLResponse, HTTPException, Path, RedirectResponse, Request, StreamingResponse, UploadFile, User, UserRole, UserStatus, WebStaffAccount, XPTransaction, compose_event_datetime, confirm_event_attendance, confirm_single_event_attendance, ctx, db, delete, delete_image, event_registration_status_label, export_event_participants_excel, export_event_participants_pdf, func, guard, guard_permission, guard_superadmin, has_web_permission, is_superadmin, label, log_audit, logging, normalize_event_xp, notify_telegram, opt_int, or_, process_event_operations, qrcode, queue_telegram_delivery, quote, save_image, select, settings, store_file_bytes, templates, timedelta, token_urlsafe, update
)
from app.media import load_file_bytes
from app.telegram_webapp import validate_webapp_init_data
from app.domain_services import admin_scan_event_participant, event_checkin_window, force_event_registration_status, reconcile_event_registration_rewards
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
            reg = EventRegistration(event_id=event.id, user_id=user.id, status="registered", registered_at=now, registration_source="scanner")
            session.add(reg)
            await session.flush()
        elif action == "register_confirm" and reg.status not in {"registered", "reserved", "checked_in"}:
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
        base_xp = int(reg.attendance_xp_awarded or 0)
        bonus_xp = int(reg.preregistration_bonus_xp_awarded or 0)
        notice = f"✅ Участь у події «{event.title}» підтверджено.\n⚡ За участь: +{base_xp} XP"
        if bonus_xp:
            notice += f"\n🎟 Бонус за попередню реєстрацію: +{bonus_xp} XP"
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
            "message": "Присутність підтверджено",
            "xp": int(reg.attendance_xp_awarded or 0) + int(reg.preregistration_bonus_xp_awarded or 0),
            "base_xp": int(reg.attendance_xp_awarded or 0), "bonus_xp": int(reg.preregistration_bonus_xp_awarded or 0),
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
            if window["state"] != "open" and not is_superadmin(request):
                raise HTTPException(status_code=403, detail="Поза часовим вікном відмітки змінювати статус участі може лише суперадміністратор.")
            if window["state"] != "open" and len(reason) < 5:
                raise HTTPException(status_code=409, detail="Суперадміністратор має вказати причину ручного підтвердження (мінімум 5 символів).")
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
        admin_user = await _scanner_actor_user(session, request)
        if event and event.status != "cancelled" and not event.cancelled_at and reg and admin_user and reg.event_id == event.id:
            window = await event_checkin_window(session, event)
            reason = override_reason.strip()
            if window["state"] != "open" and not is_superadmin(request):
                raise HTTPException(status_code=403, detail="Поза вікном відмітки підтверджувати участь може лише суперадміністратор.")
            if window["state"] != "open" and len(reason) < 5:
                raise HTTPException(status_code=409, detail="Суперадміністратор має вказати причину ручного підтвердження (мінімум 5 символів).")
            result = await confirm_single_event_attendance(session, event, reg, admin_user, override_reason=reason or None)
            if result:
                user, total, level_name, leveled = result
                base_xp = int(reg.attendance_xp_awarded or 0)
                bonus_xp = int(reg.preregistration_bonus_xp_awarded or 0)
                text = f"✅ Участь у події «{event.title}» підтверджено.\n⚡ За участь: +{base_xp} XP"
                if bonus_xp:
                    text += f"\n🎟 Бонус за попередню реєстрацію: +{bonus_xp} XP"
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
        event_started = bool(clock.event_utc(event.starts_at) and clock.event_utc(event.starts_at) <= clock.now_utc())
        if reg.status != "waitlisted" and event_started and not is_superadmin(request):
            raise HTTPException(status_code=403, detail="Після початку події скасувати реєстрацію може лише суперадміністратор. Для звичайного учасника має бути зафіксований фактичний статус участі.")
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
        window = await event_checkin_window(session, event)
        if window["state"] != "closed" and not is_superadmin(request):
            raise HTTPException(status_code=403, detail="Статус «Не прийшов» можна встановлювати після закриття вікна відмітки. Дострокове коригування доступне лише суперадміністратору.")
        actor = await _scanner_actor_user(session, request)
        reward_change = await reconcile_event_registration_rewards(
            session, event, reg, target_status="no_show", actor_user=actor
        )
        reg.status = "no_show"
        reg.no_show_at = clock.storage_utc()
        reg.reservation_expires_at = None
        user = reward_change.get("user")
        penalty = int(reward_change.get("no_show_penalty_xp") or 0)
        if user and int(reward_change.get("penalty_delta") or 0) < 0 and getattr(user, "tg_id", None):
            await queue_telegram_delivery(
                session, user.tg_id,
                f"🚫 <b>Неявка на подію без скасування</b>\n\n«<b>{event.title}</b>»\n"
                f"Статус: <b>Не прийшов</b>. Застосовано <b>-{penalty} XP</b>.\n\n"
                "Якщо плани змінюються, скасовуй реєстрацію до початку події.",
                source="event_no_show", notification_type="event", title=f"Неявка: {event.title}",
                recipient_user_id=user.id, entity_type="event_registration", entity_id=reg.id,
                dedupe_key=f"web_event_no_show_penalty:{event.id}:{reg.id}:{reg.no_show_penalty_xp_applied}",
            )
        await log_audit(session, "web_event_no_show", actor_label=request.session.get("admin_name","web"), entity_type="event", entity_id=event.id, details=f"АМП-{reg.user_id:04d}; penalty={penalty}")
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
        admin_user = await _scanner_actor_user(session, request)
        if not event or not admin_user or event.status == "cancelled" or event.cancelled_at:
            return RedirectResponse(f"/admin/events/{event_id}", 303)
        window = await event_checkin_window(session, event)
        reason = override_reason.strip()
        if window["state"] != "open" and not is_superadmin(request):
            raise HTTPException(status_code=403, detail="Поза вікном відмітки масове підтвердження доступне лише суперадміністратору.")
        if window["state"] != "open" and len(reason) < 5:
            raise HTTPException(status_code=409, detail="Суперадміністратор має вказати причину ручного підтвердження (мінімум 5 символів).")
        count, results = await confirm_event_attendance(session, event, admin_user, override_reason=reason or None)
        for user, total, level_name, leveled in results:
            reg = await session.scalar(select(EventRegistration).where(EventRegistration.event_id == event.id, EventRegistration.user_id == user.id))
            base_xp = int(reg.attendance_xp_awarded or 0) if reg else int(event.xp_reward or 0)
            bonus_xp = int(reg.preregistration_bonus_xp_awarded or 0) if reg else 0
            text = f"✅ Участь у події «{event.title}» підтверджено.\n⚡ За участь: +{base_xp} XP"
            if bonus_xp:
                text += f"\n🎟 Бонус за попередню реєстрацію: +{bonus_xp} XP"
            if event.volunteer_hours:
                text += f"\n+{event.volunteer_hours:g} волонтерських годин"
            text += f"\nВсього: {total} XP"
            if leveled:
                text += f"\n🎉 Новий рівень: {level_name}"
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
        if window["state"] != "closed" and not is_superadmin(request):
            raise HTTPException(status_code=409, detail="Масове позначення «Не прийшов» доступне лише після закриття вікна відмітки.")
        rows = list((await session.scalars(
            select(EventRegistration).where(
                EventRegistration.event_id == event.id,
                EventRegistration.status.in_(["registered", "reserved"]),
            )
        )).all())
        actor = await _scanner_actor_user(session, request)
        now = clock.storage_utc()
        penalized = 0
        for reg in rows:
            reward_change = await reconcile_event_registration_rewards(
                session, event, reg, target_status="no_show", actor_user=actor
            )
            reg.status = "no_show"
            reg.no_show_at = now
            reg.reservation_expires_at = None
            if int(reward_change.get("penalty_delta") or 0) < 0:
                penalized += 1
                user = reward_change.get("user")
                penalty = int(reward_change.get("no_show_penalty_xp") or 0)
                if user and getattr(user, "tg_id", None):
                    await queue_telegram_delivery(
                        session, user.tg_id,
                        f"🚫 <b>Неявка на подію без скасування</b>\n\n«<b>{event.title}</b>»\n"
                        f"Статус: <b>Не прийшов</b>. Застосовано <b>-{penalty} XP</b>.\n\n"
                        "Якщо плани змінюються, скасовуй реєстрацію до початку події.",
                        source="event_no_show", notification_type="event", title=f"Неявка: {event.title}",
                        recipient_user_id=user.id, entity_type="event_registration", entity_id=reg.id,
                        dedupe_key=f"web_event_bulk_no_show:{event.id}:{reg.id}:{reg.no_show_penalty_xp_applied}",
                    )
        await log_audit(
            session, "web_event_operations_bulk_no_show",
            actor_label=request.session.get("admin_name", "web"), entity_type="event", entity_id=event.id,
            details=f"Масово позначено «Не прийшов»: {len(rows)}; штраф застосовано: {penalized}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}#event-operations", 303)


@router.post("/admin/events/{event_id}/registrations/{registration_id}/status")
async def superadmin_force_event_registration_status(
    request: Request, event_id: int, registration_id: int, status: str = Form(...), reason: str = Form(...),
):
    if r := guard_superadmin(request):
        return r
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=409, detail="Для ручної зміни статусу суперадміністратор має вказати причину щонайменше з 5 символів.")
    async with db.session_factory() as session:
        event = await session.get(Event, event_id)
        reg = await session.get(EventRegistration, registration_id)
        if not event or not reg or reg.event_id != event.id:
            raise HTTPException(status_code=404, detail="Реєстрацію не знайдено")
        admin_user = await _scanner_actor_user(session, request)
        if not admin_user or admin_user.role != UserRole.SUPERADMIN.value:
            admin_user = await session.scalar(select(User).where(User.role == UserRole.SUPERADMIN.value).order_by(User.id.asc()))
        if not admin_user:
            raise HTTPException(status_code=409, detail="Не знайдено профіль суперадміністратора для аудиту XP.")
        try:
            reward_change = await force_event_registration_status(session, event, reg, status, admin_user)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        user = reward_change.get("user")
        previous_status = str(reward_change.get("previous_status") or "")
        parts = []
        base_delta = int(reward_change.get("base_delta") or 0)
        bonus_delta = int(reward_change.get("bonus_delta") or 0)
        penalty_delta = int(reward_change.get("penalty_delta") or 0)
        hours_delta = float(reward_change.get("hours_delta") or 0)
        if base_delta:
            parts.append(f"{base_delta:+d} XP за участь")
        if bonus_delta:
            parts.append(f"{bonus_delta:+d} XP бонусу")
        if penalty_delta:
            parts.append(f"{penalty_delta:+d} XP коригування штрафу")
        if hours_delta:
            parts.append(f"{hours_delta:+g} год.")
        await log_audit(
            session, "web_event_registration_status_override", actor_label=request.session.get("admin_name", "web"),
            entity_type="event", entity_id=event.id,
            details=f"Реєстрація #{reg.id}; {previous_status} -> {status}; reason={reason}; rewards={'; '.join(parts) or 'без змін'}",
        )
        if user and getattr(user, "tg_id", None):
            adjustment = ("\n⚡ Коригування: " + "; ".join(parts)) if parts else ""
            await queue_telegram_delivery(
                session, user.tg_id,
                f"ℹ️ <b>Статус участі у події змінено</b>\n\n«<b>{event.title}</b>»\n"
                f"Новий статус: <b>{event_registration_status_label(status)}</b>.{adjustment}\n\n"
                f"Причина: {reason}",
                source="event_status_override", notification_type="event", title=f"Статус участі: {event.title}",
                recipient_user_id=user.id, entity_type="event_registration", entity_id=reg.id,
                dedupe_key=f"event_status_override:{event.id}:{reg.id}:{status}:{reg.updated_at if hasattr(reg, 'updated_at') else clock.storage_utc().isoformat()}",
            )
        await session.commit()
    return RedirectResponse(f"/admin/events/{event_id}#event-participants", 303)
