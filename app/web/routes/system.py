from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
import os
from app.web.dependencies import (
    APP_VERSION, AuditLog, Bot, BroadcastCampaign, BroadcastRecipient, BytesIO, HTMLResponse, MediaAsset, Notification, RedirectResponse, Referral, Request, ScheduledJob, StreamingResponse, SystemSetting, User, asyncio, ctx, datetime, db, export_basic_excel, export_excel, func, guard, guard_permission, latest_local_backup, log_audit, reliability_counts, select, settings, templates, timedelta
)
from app.reliability import backup_verification_status
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/help", response_class=HTMLResponse)
async def help_page(request: Request):
    if r := guard(request): return r
    return templates.TemplateResponse(request=request, name="help.html", context=ctx(request))


@router.get("/admin/referrals", response_class=HTMLResponse)
async def referrals(request:Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        rows=(await session.execute(select(Referral,User.full_name).join(User,User.id==Referral.inviter_user_id).order_by(Referral.created_at.desc()).limit(300))).all(); invited_names={u.id:u.full_name for u in (await session.scalars(select(User))).all()}
        return templates.TemplateResponse(request=request,name="referrals.html",context=ctx(request,rows=rows,invited_names=invited_names))


@router.get("/admin/audit", response_class=HTMLResponse)
async def audit(request:Request):
    if r := guard_permission(request, "audit.view"): return r
    async with db.session_factory() as session:
        rows=(await session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500))).all(); return templates.TemplateResponse(request=request,name="audit.html",context=ctx(request,rows=rows))


@router.get("/admin/audit/{log_id}", response_class=HTMLResponse)
async def audit_detail(request: Request, log_id: int):
    if r := guard_permission(request, "audit.view"): return r
    async with db.session_factory() as session:
        row = await session.get(AuditLog, log_id)
        if not row:
            return HTMLResponse("Запис журналу не знайдено", status_code=404)
        return templates.TemplateResponse(request=request, name="audit_detail.html", context=ctx(request, row=row))


@router.get("/admin/export")
async def export(request: Request):
    """Data-minimized operational workbook."""
    if r := guard(request): return r
    async with db.session_factory() as session:
        data = await export_basic_excel(session)
        await log_audit(session, "web_export_basic", actor_label=request.session.get("admin_name", "web"), entity_type="export", details="Завантажено базовий Excel без чутливих персональних даних")
        await session.commit()
    return StreamingResponse(BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="AMPasadori_basic_export.xlsx"'})


@router.get("/admin/export/sensitive")
async def export_sensitive(request: Request):
    """Full workbook with sensitive participant data; superadmin only."""
    if r := guard_permission(request, "reports.sensitive_export"): return r
    async with db.session_factory() as session:
        data = await export_excel(session)
        await log_audit(session, "web_export_sensitive", actor_label=request.session.get("admin_name", "web"), entity_type="export", details="Завантажено розширений Excel із персональними та чутливими даними")
        await session.commit()
    return StreamingResponse(BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="AMPasadori_sensitive_export.xlsx"'})


@router.get("/admin/system-health", response_class=HTMLResponse)
async def system_health(request: Request):
    """Operational health overview without requiring Heroku CLI."""
    if r := guard(request):
        return r

    now = clock.storage_utc()
    db_ok = True
    db_error = ""
    bot_ok = False
    bot_label = "Не налаштовано"
    jobs = []
    latest_job = None
    backup_label = "Немає даних"
    backup_at = None
    backup_status = {"ok": False, "status": "unknown", "age_hours": None}
    pending_notifications = failed_notifications = 0
    failed_broadcasts = pending_broadcasts = 0
    media_count = media_bytes = 0

    try:
        async with db.session_factory() as session:
            await session.execute(select(1))
            jobs = list((await session.scalars(
                select(ScheduledJob).order_by(ScheduledJob.job_name.asc())
            )).all())
            latest_job = max(
                (j for j in jobs if j.last_success_at),
                key=lambda j: j.last_success_at,
                default=None,
            )
            counts = await reliability_counts(session)
            pending_notifications = counts["pending_notifications"]
            failed_notifications = counts["failed_notifications"]
            failed_broadcasts = int(await session.scalar(
                select(func.count(BroadcastCampaign.id)).where(
                    BroadcastCampaign.status.in_(["failed", "completed_with_errors"])
                )
            ) or 0)
            pending_broadcasts = int(await session.scalar(
                select(func.count(BroadcastRecipient.id)).where(
                    BroadcastRecipient.status.in_(["pending", "retry"])
                )
            ) or 0)
            media_count = int(await session.scalar(select(func.count(MediaAsset.id))) or 0)
            media_bytes = int(await session.scalar(select(func.coalesce(func.sum(MediaAsset.size_bytes), 0))) or 0)
            marker = await session.get(SystemSetting, "last_backup_at")
            if marker and marker.value:
                raw = marker.value.split("|", 1)
                try:
                    backup_at = datetime.fromisoformat(raw[0])
                except ValueError:
                    backup_at = None
                backup_label = raw[1] if len(raw) > 1 else "Зафіксована резервна копія"
            backup_status = await backup_verification_status(
                session, unknown_grace_hours=settings.backup_unknown_grace_hours
            )
    except Exception as exc:
        db_ok = False
        db_error = str(exc)[:300]

    local_backup_name, local_backup_at = await latest_local_backup(settings.data_dir)
    if local_backup_at and (not backup_at or local_backup_at > backup_at):
        backup_at = local_backup_at
        backup_label = local_backup_name or "Локальна резервна копія"
        age_hours = max(0.0, (now - local_backup_at).total_seconds() / 3600)
        if backup_status.get("status") == "unknown":
            backup_status = {"ok": age_hours <= 168, "status": "ok" if age_hours <= 168 else "stale", "age_hours": round(age_hours, 1)}

    if settings.bot_token:
        bot = Bot(settings.bot_token)
        try:
            me = await asyncio.wait_for(bot.get_me(), timeout=5)
            bot_ok = True
            bot_label = f"@{me.username}" if me.username else me.full_name
        except Exception as exc:
            bot_label = f"Помилка перевірки: {str(exc)[:100]}"
        finally:
            await bot.session.close()

    active_locks = sum(1 for j in jobs if j.locked_until and j.locked_until > now)
    recent_success = any(j.last_success_at and (now - j.last_success_at) <= timedelta(hours=2) for j in jobs)
    scheduler_ok = bool(active_locks or recent_success)
    scheduler_label = "Працює" if scheduler_ok else ("Очікує першого успішного запуску" if jobs else "Ще немає записів")

    release_version = os.getenv("HEROKU_RELEASE_VERSION", "").strip() or "—"
    source_version = os.getenv("HEROKU_SLUG_COMMIT", "").strip() or os.getenv("SOURCE_VERSION", "").strip() or "—"
    dyno = os.getenv("DYNO", "").strip() or "local"

    return templates.TemplateResponse(
        request=request,
        name="system_health.html",
        context=ctx(
            request,
            now=now,
            db_ok=db_ok,
            db_error=db_error,
            bot_ok=bot_ok,
            bot_label=bot_label,
            scheduler_ok=scheduler_ok,
            scheduler_label=scheduler_label,
            active_locks=active_locks,
            jobs=jobs,
            latest_job=latest_job,
            backup_at=backup_at,
            backup_label=backup_label,
            backup_status=backup_status,
            pending_notifications=pending_notifications,
            failed_notifications=failed_notifications,
            failed_broadcasts=failed_broadcasts,
            pending_broadcasts=pending_broadcasts,
            pending_jobs=pending_notifications + pending_broadcasts,
            media_count=media_count,
            media_bytes=media_bytes,
            app_version=APP_VERSION,
            release_version=release_version,
            source_version=source_version,
            dyno=dyno,
        ),
    )

@router.post("/admin/system-health/retry-failed-notifications")
async def retry_failed_notifications(request: Request):
    if r := guard(request):
        return r
    now = clock.storage_utc()
    async with db.session_factory() as session:
        rows = list((await session.scalars(
            select(Notification).where(Notification.status == "failed").limit(500)
        )).all())
        for row in rows:
            row.status = "retry"
            row.retry_count = 0
            row.scheduled_at = now
            row.error = ""
            row.updated_at = now
        await log_audit(
            session, "web_retry_failed_notifications", actor_label=request.session.get("admin_name", "web"),
            entity_type="notification", details=f"Повернуто в retry: {len(rows)}",
        )
        await session.commit()
    return RedirectResponse("/admin/system-health#telegram-delivery", 303)
