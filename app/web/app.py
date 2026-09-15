from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging
import json
import hashlib
import os
from datetime import datetime, date, timedelta
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4
from urllib.parse import quote
from html import escape as html_escape

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps
import qrcode
from sqlalchemy import case as sql_case, delete, func, or_, select, update
from starlette.middleware.sessions import SessionMiddleware
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from ..config import get_settings
from ..observability import RequestContextMiddleware
from ..db import Database
from ..gamification import AUTOMATIC_XP_GUIDE, get_level, normalize_event_xp, normalize_manual_xp, normalize_quest_xp, normalize_task_xp
from ..models import (
    ActivityApplication, ActivityType,
    AuditLog, BanRecord, Badge, BroadcastCampaign, BroadcastRecipient, BroadcastTemplate, Event, EventRegistration, Goal, Idea, MediaAsset, Opportunity, OpportunityInterest, Quest, QuestParticipation, Referral, RequestCase, Reward, RewardClaim, Season, SystemSetting, Team, TeamQuestContribution,
    User, UserBadge, UserRole, UserStatus, VolunteerTask, VolunteerTaskParticipation, XPTransaction, RequestMessage, GoalReward, ConsentHistory,
    Survey, SurveyQuestion, SurveyResponse, UserStatusChangeRequest, ParticipationStreak, StreakFreeze,
    WebStaffAccount, WebAdminSession, ScheduledJob, NotificationDelivery, Notification, EventFeedback,
)
from ..ui_labels import ACTIVITY_CATEGORY_OPTIONS, action_description, action_title, activity_category_label, activity_status_label, idea_status_label, label, lifecycle_status_label, request_status_label, event_registration_status_label
from ..profile_data import MEDIA_CONSENT_VERSION, GENDER_OPTIONS, VULNERABILITY_OPTIONS, dump_vulnerabilities, gender_label, load_vulnerabilities, media_consent_label, vulnerability_labels
from ..media import delete_stored_image, store_image_bytes, store_file_bytes, store_transparent_png
from ..permissions import PERMISSION_GROUPS, dump_permissions, effective_permissions
from ..security import (
    LOGIN_LOCK_MINUTES, LOGIN_MAX_ATTEMPTS, OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES,
    browser_label, client_ip, generate_csrf_token, generate_otp, generate_session_token,
    generate_temporary_password, hash_password, media_access_level, otp_hash, password_errors,
    session_expiry, token_hash, verify_otp, verify_password,
)
from .security_middleware import AdminSessionValidationMiddleware, CSRFMiddleware, SecurityHeadersMiddleware
from ..broadcasts import BROADCAST_TEMPLATES, audience_description, personalize_message, resolve_broadcast_audience, template_options
from ..analytics import METRIC_META, analytics_bot_text, analytics_excel, analytics_pdf, analytics_png, build_analytics
from ..reports import build_period_report, report_excel, report_pdf, resolve_report_period
from ..engagement import GOAL_METRIC_LABELS, goal_progress, process_expired_content
from ..leagues import LEAGUES, MAX_FREEZE_DAYS_PER_QUARTER, create_streak_freeze, league_counts, league_for_xp, refresh_all_streaks, refresh_user_streak, season_leaderboard_rows, streak_freeze_summary
from ..version import APP_VERSION
from ..reliability import job_lock, latest_local_backup, reliability_counts, queue_telegram_delivery
from ..runtime_health import (
    alembic_revision_status, database_probe, expected_alembic_head, heartbeat_loop,
    runtime_health_alert, runtime_health_snapshot, scheduler_heartbeat,
)
from ..survey_exports import build_survey_stats, survey_excel, survey_pdf, survey_question_png
from ..workflows import approve_quest_participation, approve_volunteer_task_participation, award_idea_approval_once
from ..services import (
    add_active_users_to_default_team, add_xp, age_on, bootstrap_defaults, complete_activity_application, complete_team_quest, confirm_event_attendance,
    confirm_single_event_attendance,
    current_season, evaluate_automatic_badges, export_basic_excel, export_event_participants_excel, export_event_participants_pdf, export_excel, log_audit, process_expired_bans, process_event_operations,
    reward_referral_if_ready, revoke_referral_reward_if_inactive, season_xp, seed_default_team, xp_total,
)

settings = get_settings(require_bot_token=False)
db = Database(settings)
templates = Jinja2Templates(directory="app/web/templates")
templates.env.globals.update(label=label, idea_status_label=idea_status_label, activity_status_label=activity_status_label, activity_category_label=activity_category_label, activity_category_options=ACTIVITY_CATEGORY_OPTIONS, request_status_label=request_status_label, lifecycle_status_label=lifecycle_status_label, event_registration_status_label=event_registration_status_label, action_title=action_title, action_description=action_description)
UPLOAD_ROOT = Path(settings.data_dir) / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
for folder in ("events", "rewards", "quests", "tasks", "requests"):
    (UPLOAD_ROOT / folder).mkdir(parents=True, exist_ok=True)


async def _refresh_lifecycle(session) -> dict[str, int]:
    """Persist deadline-based status changes immediately when a page is opened."""
    changed = await process_expired_content(session)
    event_ops = await process_event_operations(session)
    combined = dict(changed)
    for key, value in event_ops.items():
        if value:
            combined[key] = combined.get(key, 0) + int(value)
    if combined:
        await log_audit(session, "system_auto_complete", actor_label="Система АМП", entity_type="system", details=str(combined))
        await session.commit()
    return combined


async def _runtime_health_monitor_loop(bot: Bot) -> None:
    # Give the worker enough time to boot after a deploy before declaring it
    # missing. Subsequent checks run from web, so a dead worker can still raise
    # a direct Telegram alarm to superadmins.
    await asyncio.sleep(settings.health_startup_grace_seconds)
    while True:
        try:
            await runtime_health_alert(
                bot, db, settings,
                repeat_seconds=settings.scheduler_alert_repeat_seconds,
                worker_stale_seconds=settings.worker_stale_seconds,
                startup_grace_seconds=settings.health_startup_grace_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger("amp.runtime_health").exception("Помилка runtime health monitor")
        await asyncio.sleep(60)


async def lifespan(app: FastAPI):
    smoke_mode = os.getenv("AMP_STARTUP_SMOKE", "").strip() == "1"
    app.state.startup_complete = False
    await db.init()
    await bootstrap_defaults(db, settings)

    background_tasks: list[asyncio.Task] = []
    health_bot: Bot | None = None
    if not smoke_mode:
        await _retire_legacy_version_broadcasts()
        await _recover_pending_broadcasts()
        await _announce_version_update()
        # Deadline/status housekeeping belongs to worker. The web process keeps
        # only broadcast recovery plus production health monitoring.
        background_tasks.append(asyncio.create_task(_broadcast_retry_scheduler(), name="broadcast_retry_scheduler"))
        background_tasks.append(asyncio.create_task(
            heartbeat_loop(db, "web", interval_seconds=settings.worker_heartbeat_seconds),
            name="web_heartbeat",
        ))
        if settings.bot_token and settings.superadmin_ids:
            health_bot = Bot(settings.bot_token)
            background_tasks.append(asyncio.create_task(
                _runtime_health_monitor_loop(health_bot), name="runtime_health_monitor"
            ))

    app.state.startup_complete = True
    try:
        yield
    finally:
        app.state.startup_complete = False
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        for task in list(_broadcast_tasks):
            task.cancel()
        if _broadcast_tasks:
            await asyncio.gather(*list(_broadcast_tasks), return_exceptions=True)
        if health_bot is not None:
            await health_bot.session.close()
        await db.close()



app = FastAPI(title="АМПасадори — панель керування", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware, service="web")
# Add inner security middleware first; SessionMiddleware is added last so it wraps
# them and makes the signed session available for CSRF/session validation.
app.add_middleware(AdminSessionValidationMiddleware, db=db)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SessionMiddleware, secret_key=settings.web_session_secret, same_site="strict", https_only=settings.cookie_secure, max_age=60*60*24*30)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


def _health_response(payload: dict, status_code: int = 200) -> JSONResponse:
    # runtime health snapshots intentionally keep native datetime objects for
    # internal/admin consumers. Encode only at the HTTP boundary so health
    # endpoints can always return valid JSON instead of raising TypeError.
    return JSONResponse(jsonable_encoder(payload), status_code=status_code, headers={"Cache-Control": "no-store"})


@app.get("/health/live")
async def health_live():
    """Process liveness only; never contacts external dependencies."""
    return _health_response({"status": "ok", "service": "web", "version": APP_VERSION})


@app.get("/health/ready")
async def health_ready():
    """Web readiness: startup completed, PostgreSQL answers and Alembic is at head."""
    startup_complete = bool(getattr(app.state, "startup_complete", False))
    db_status = await database_probe(db, timeout_seconds=settings.health_probe_timeout_seconds)
    migration = {"ok": False, "current": None, "expected": expected_alembic_head()}
    if db_status["ok"]:
        migration = await alembic_revision_status(db, expected_head=migration["expected"] or "")
    ready = bool(startup_complete and db_status["ok"] and migration.get("ok"))
    return _health_response(
        {
            "status": "ready" if ready else "not_ready",
            "version": APP_VERSION,
            "startup_complete": startup_complete,
            "database": db_status,
            "alembic": migration,
        },
        200 if ready else 503,
    )


@app.get("/health/dependencies")
async def health_dependencies():
    """Full system dependency status for external monitoring and diagnostics."""
    db_status = await database_probe(db, timeout_seconds=settings.health_probe_timeout_seconds)
    expected_head = expected_alembic_head()
    migration = {"ok": False, "current": None, "expected": expected_head}
    runtime = {"ok": False, "worker_ok": False, "schedulers_ok": False, "worker": {}, "schedulers": []}
    if db_status["ok"]:
        migration = await alembic_revision_status(db, expected_head=expected_head)
        try:
            async with db.session_factory() as session:
                runtime = await runtime_health_snapshot(
                    session,
                    worker_stale_seconds=settings.worker_stale_seconds,
                    startup_grace_seconds=settings.health_startup_grace_seconds,
                )
        except Exception as exc:
            runtime = {
                "ok": False, "worker_ok": False, "schedulers_ok": False,
                "worker": {}, "schedulers": [], "error": type(exc).__name__,
            }
    overall = bool(db_status["ok"] and migration.get("ok") and runtime.get("ok"))
    return _health_response(
        {
            "status": "ok" if overall else "degraded",
            "version": APP_VERSION,
            "database": db_status,
            "pool": db.pool_status(),
            "alembic": migration,
            "worker": runtime.get("worker", {}),
            "schedulers_ok": runtime.get("schedulers_ok", False),
            "schedulers": runtime.get("schedulers", []),
        },
        200 if overall else 503,
    )


@app.get("/health")
async def health():
    """Backward-compatible lightweight liveness endpoint."""
    return _health_response({"status": "ok", "version": APP_VERSION})


def logged_in(request: Request) -> bool:
    return bool(request.session.get("admin_auth"))


def web_role(request: Request) -> str:
    return str(request.session.get("admin_role") or "")


def web_permissions(request: Request) -> frozenset[str]:
    stored = request.session.get("admin_permissions") or []
    if web_role(request) == UserRole.SUPERADMIN.value:
        return effective_permissions(UserRole.SUPERADMIN.value, None)
    return frozenset(str(item) for item in stored)


def has_web_permission(request: Request, permission: str) -> bool:
    return logged_in(request) and permission in web_permissions(request)


def is_superadmin(request: Request) -> bool:
    return logged_in(request) and web_role(request) == "superadmin"


def guard(request: Request):
    if not logged_in(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


def guard_permission(request: Request, permission: str):
    if r := guard(request):
        return r
    if not has_web_permission(request, permission):
        return HTMLResponse(
            f"<h1>403</h1><p>Недостатньо прав для цієї дії: <code>{permission}</code>.</p>",
            status_code=403,
        )
    return None


def guard_superadmin(request: Request):
    if r := guard(request):
        return r
    if not is_superadmin(request):
        return HTMLResponse(
            "<h1>403</h1><p>Цей розділ доступний лише суперадміністратору.</p>",
            status_code=403,
        )
    return None


def mask_phone(value: str | None) -> str:
    if not value:
        return "—"
    text = str(value).strip()
    digits = [i for i, ch in enumerate(text) if ch.isdigit()]
    if len(digits) <= 4:
        return "••••"
    keep = set(digits[:3] + digits[-2:])
    return "".join(ch if (not ch.isdigit() or i in keep) else "•" for i, ch in enumerate(text))


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return "—" if not value else "•••"
    local, domain = value.split("@", 1)
    if not local:
        return f"•••@{domain}"
    return f"{local[0]}•••@{domain}"


def _csrf_token(request: Request) -> str:
    token = str(request.session.get("csrf_token") or "")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return token


def ctx(request: Request, **kwargs):
    return {
        "request": request,
        "settings": settings,
        "admin_name": request.session.get("admin_name", ""),
        "admin_role": web_role(request),
        "is_superadmin": is_superadmin(request),
        "admin_permissions": web_permissions(request),
        "has_permission": lambda permission: has_web_permission(request, permission),
        "csrf_token": _csrf_token(request),
        "mask_phone": mask_phone,
        "mask_email": mask_email,
        **kwargs,
    }


async def save_image(upload: UploadFile | None, category: str) -> str | None:
    """Validate, normalize and store an uploaded image.

    Local installs store files under AMP_Bot_Data. PostgreSQL/Heroku installs
    use database-backed media so uploads survive dyno restarts and deploys.
    """
    if not upload or not upload.filename:
        return None
    if upload.content_type and not upload.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Дозволено завантажувати лише зображення.")
    raw = await upload.read()
    if not raw:
        return None
    max_bytes = 20 * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="Зображення завелике. Максимальний розмір файлу — 20 МБ.")
    try:
        return await store_image_bytes(db, raw, category, original_name=upload.filename or "image")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def save_badge_png(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None
    if (upload.content_type or "").lower() != "image/png" and not upload.filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Для бейджів АМПасадора завантажуйте PNG із прозорим фоном.")
    raw = await upload.read()
    if not raw:
        return None
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PNG завеликий. Максимум — 20 МБ.")
    try:
        return await store_transparent_png(db, raw, "ambassador_badges", original_name=upload.filename or "badge.png")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def save_document(upload: UploadFile | None, category: str) -> str | None:
    if not upload or not upload.filename:
        return None
    raw = await upload.read()
    if not raw:
        return None
    max_bytes = 20 * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="Файл завеликий. Максимальний розмір — 20 МБ.")
    allowed = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
    ctype = upload.content_type or "application/octet-stream"
    if ctype not in allowed and not ctype.startswith("image/"):
        raise HTTPException(status_code=400, detail="Дозволені PDF, JPG, PNG або WebP.")
    return await store_file_bytes(db, raw, category, original_name=upload.filename or "document", content_type=ctype)


async def delete_image(path: str | None) -> None:
    await delete_stored_image(db, path)


@app.get("/media/{asset_id}")
async def media_asset(request: Request, asset_id: int):
    """Serve DB media according to explicit access classification.

    Public artwork is cacheable. Evidence, case attachments and documents are
    never exposed to anonymous direct URLs. Sensitive views are audited.
    """
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Файл не знайдено")
        level = media_access_level(asset.category)
        if level != "public":
            if not logged_in(request):
                raise HTTPException(status_code=404, detail="Файл не знайдено")
            if level == "superadmin_private" and not is_superadmin(request):
                raise HTTPException(status_code=404, detail="Файл не знайдено")
            await log_audit(
                session,
                "web_sensitive_media_view",
                actor_label=request.session.get("admin_name", "web"),
                entity_type="media_asset",
                entity_id=asset.id,
                details=f"category={asset.category}; access={level}",
            )
            await session.commit()
        return Response(
            content=asset.data,
            media_type=asset.content_type or "application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=86400" if level == "public" else "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


@app.get("/uploads/{category}/{filename}")
async def categorized_upload_file(request: Request, category: str, filename: str):
    """Serve legacy/local uploads through the same category access policy.

    This intentionally replaces the old public StaticFiles /uploads mount so
    historic request/evidence files can no longer be fetched anonymously.
    """
    level = media_access_level(category)
    if level != "public":
        if not logged_in(request):
            raise HTTPException(status_code=404, detail="Файл не знайдено")
        if level == "superadmin_private" and not is_superadmin(request):
            raise HTTPException(status_code=404, detail="Файл не знайдено")
    root = (Path(settings.data_dir) / "uploads" / category).resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    content_type = {
        ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    if level != "public":
        async with db.session_factory() as session:
            await log_audit(
                session, "web_sensitive_media_view", actor_label=request.session.get("admin_name", "web"),
                entity_type="legacy_media", details=f"category={category}; file={filename}; access={level}",
            )
            await session.commit()
    return Response(
        content=path.read_bytes(), media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400" if level == "public" else "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/private/{category}/{filename}")
async def private_media_file(request: Request, category: str, filename: str):
    """Serve local-development private media through the same role policy."""
    level = media_access_level(category)
    if level == "public":
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    if not logged_in(request):
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    if level == "superadmin_private" and not is_superadmin(request):
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    root = (Path(settings.data_dir) / "private" / category).resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    content_type = {
        ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    async with db.session_factory() as session:
        await log_audit(
            session, "web_sensitive_media_view", actor_label=request.session.get("admin_name", "web"),
            entity_type="private_media", details=f"category={category}; file={filename}; access={level}",
        )
        await session.commit()
    return Response(
        content=path.read_bytes(), media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


MONTH_NAMES_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}

def compose_event_datetime(day: int, month: int, year: int, event_time: str) -> datetime:
    """Build an event datetime from separate human-friendly date fields."""
    try:
        hour, minute = [int(x) for x in event_time.strip().split(":", 1)]
        return datetime(int(year), int(month), int(day), hour, minute)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Перевірте день, місяць, рік і час події.") from exc


def compose_optional_datetime_fields(
    day: str | int | None,
    month: str | int | None,
    year: str | int | None,
    time_value: str | None,
    *,
    entity_label: str = "дедлайну",
) -> datetime | None:
    """Build an optional datetime from separate date/time inputs. All four fields must be filled or all left blank."""
    values = [str(day or "").strip(), str(month or "").strip(), str(year or "").strip(), (time_value or "").strip()]
    if not any(values):
        return None
    if not all(values):
        raise HTTPException(status_code=400, detail=f"Для {entity_label} заповніть день, місяць, рік і час або залиште всі поля порожніми.")
    try:
        hour, minute = [int(x) for x in values[3].split(":", 1)]
        return datetime(int(values[2]), int(values[1]), int(values[0]), hour, minute)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Перевірте день, місяць, рік і час {entity_label}.") from exc

def opt_int(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def notify_telegram(
    tg_id: int | None,
    text: str,
    *,
    source: str = "web_notification",
    title: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    button_text: str | None = None,
    callback_data: str | None = None,
) -> None:
    """Queue a reliable Telegram notification instead of dropping transient failures."""
    if not tg_id or not settings.bot_token:
        return
    try:
        async with db.session_factory() as session:
            await queue_telegram_delivery(
                session,
                tg_id,
                text,
                source=source,
                title=title,
                entity_type=entity_type,
                entity_id=entity_id,
                parse_mode="HTML",
                button_text=button_text,
                callback_data=callback_data,
            )
            await session.commit()
    except Exception:
        logging.getLogger("amp.web_notifications").exception("Не вдалося поставити Telegram-повідомлення в чергу")



_broadcast_tasks: set[asyncio.Task] = set()


def _track_broadcast_task(task: asyncio.Task) -> None:
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)


def _schedule_broadcast(campaign_id: int) -> None:
    _track_broadcast_task(asyncio.create_task(_deliver_broadcast_campaign(campaign_id), name=f"broadcast_{campaign_id}"))


async def _queue_system_broadcast(
    session,
    users: list[User],
    message_text: str,
    *,
    author_label: str,
    audience_label: str,
    template_code: str,
) -> None:
    """Queue system audience messages in the canonical v1.9 Notification Center.

    The legacy BroadcastCampaign tables stay available for manual communication
    campaigns and historical audit, but automatic entity notices no longer create
    a parallel delivery pipeline.
    """
    unique: dict[int, User] = {}
    for user in users:
        if user and user.tg_id and user.status == UserStatus.ACTIVE.value:
            unique[user.id] = user
    recipients = list(unique.values())
    if not recipients:
        return None
    digest = hashlib.sha256(message_text.strip().encode("utf-8")).hexdigest()[:16]
    for user in recipients:
        await queue_telegram_delivery(
            session, user.tg_id, message_text.strip(),
            source=template_code or "system",
            title=audience_label[:180],
            recipient_user_id=user.id,
            dedupe_key=f"system_notice:{template_code}:{digest}:user:{user.id}",
        )
    return None


def _entity_notice_text(entity_label: str, title: str, reason: str, *, deleted: bool = False) -> str:
    reason = (reason or "").strip()
    action = "скасовано та видалено із системи" if deleted else "скасовано"
    return (
        f"⚠️ {entity_label} «{title}» {action}.\n\n"
        f"Вибачте, {entity_label.lower()} «{title}» {action} через: {reason}.\n\n"
        "Прийміть наші вибачення. Дякуємо за розуміння 💙"
    )

def _postponed_notice_text(entity_label: str, title: str, new_at: datetime, reason: str) -> str:
    return (
        f"📅 {entity_label} «{title}» перенесено.\n\n"
        f"Нова актуальна дата та час: <b>{new_at.strftime('%d.%m.%Y о %H:%M')}</b>.\n"
        f"Причина: {reason.strip()}.\n\n"
        "Перепрошуємо за зміни та дякуємо за розуміння 💙"
    )



async def _retire_legacy_version_broadcasts() -> None:
    """Stop queued legacy `system_update` campaigns before recovery.

    v1.8.2.4 and older delivered version notices through BroadcastCampaign. If
    a deploy restarted while such a campaign was still queued/sending, startup
    recovery could resume it and the new startup notifier could create another
    notice. v1.8.2.5 uses the deduplicated outbox instead, so unfinished legacy
    version campaigns are explicitly retired before `_recover_pending_broadcasts`.
    """
    try:
        async with db.session_factory() as session:
            ids = list((await session.scalars(
                select(BroadcastCampaign.id).where(
                    BroadcastCampaign.source == "system",
                    BroadcastCampaign.template_code == "system_update",
                    BroadcastCampaign.status.in_(["queued", "sending"]),
                )
            )).all())
            if not ids:
                return
            now = datetime.utcnow()
            await session.execute(
                update(BroadcastCampaign)
                .where(BroadcastCampaign.id.in_(ids))
                .values(status="completed_with_errors", completed_at=now)
            )
            await session.execute(
                update(BroadcastRecipient)
                .where(
                    BroadcastRecipient.campaign_id.in_(ids),
                    BroadcastRecipient.status.in_(["pending", "retry"]),
                )
                .values(
                    status="failed",
                    next_retry_at=None,
                    error_text="Superseded by idempotent version outbox v1.8.2.5",
                )
            )
            await log_audit(
                session,
                "legacy_version_broadcast_retired",
                actor_label="Система АМП",
                entity_type="broadcast",
                details=f"Зупинено незавершених legacy version campaigns: {len(ids)}.",
            )
            await session.commit()
    except Exception:
        logging.getLogger(__name__).exception("Не вдалося завершити legacy version campaigns")


async def _announce_version_update() -> None:
    """Notify participants once per deployed APP_VERSION across concurrent dynos.

    The database lease closes the race where two startup processes both read the
    previous SystemSetting before either one commits, which used to create two
    identical version broadcasts.
    """
    try:
        async with job_lock(db, f"version_announce:{APP_VERSION}", ttl_seconds=300) as acquired:
            if not acquired:
                return
            await _announce_version_update_locked()
    except Exception:
        logging.getLogger(__name__).exception("Не вдалося підготувати одноразове повідомлення про версію")


async def _announce_version_update_locked() -> None:
    """Queue exactly one version notice per participant and APP_VERSION.

    Older releases created a normal BroadcastCampaign at startup. In practice a
    campaign could be recovered/scheduled by more than one startup path, which
    made duplicate version messages possible. Version announcements now use the
    durable Telegram outbox directly with a UNIQUE per-user dedupe key.

    Idempotency layers:
      1. distributed startup job lock;
      2. SystemSetting last_announced_app_version;
      3. UNIQUE notification_deliveries.dedupe_key per version + user.
    """
    async with db.session_factory() as session:
        state = await session.get(SystemSetting, "last_announced_app_version")
        if state and state.value == APP_VERSION:
            return

        users = list((await session.scalars(
            select(User).where(
                User.status == UserStatus.ACTIVE.value,
                User.tg_id.is_not(None),
            ).order_by(User.id.asc())
        )).all())

        message = (
            f"🔄 АМПасадори оновлено до версії v{APP_VERSION}!\n\n"
            "Ми оновили Telegram-бот і систему АМП: додали нові можливості та виправлення. "
            "Усі ваші XP, реєстрації та історія активності збережені.\n\n"
            "Щоб побачити актуальне меню, натисніть /menu або /start. 💙"
        )
        queued = 0
        for user in users:
            row = await queue_telegram_delivery(
                session,
                user.tg_id,
                message,
                source="system_version_update",
                dedupe_key=f"system_version_update:{APP_VERSION}:user:{user.id}",
                parse_mode="HTML",
            )
            if row is not None:
                queued += 1

        now = datetime.utcnow()
        if state:
            state.value = APP_VERSION
            state.updated_at = now
        else:
            session.add(SystemSetting(key="last_announced_app_version", value=APP_VERSION, updated_at=now))
        await log_audit(
            session,
            "system_version_update",
            actor_label="Система АМП",
            entity_type="system",
            details=(
                f"Зафіксовано запуск версії v{APP_VERSION}; "
                f"активних одержувачів: {len(users)}; outbox записів: {queued}."
            ),
        )
        await session.commit()


async def _recover_pending_broadcasts() -> None:
    """Resume queued/interrupted campaigns after a dyno restart or deploy."""
    try:
        async with db.session_factory() as session:
            ids = (await session.scalars(
                select(BroadcastCampaign.id).where(BroadcastCampaign.status.in_(["queued", "sending"]))
            )).all()
        for campaign_id in ids:
            _schedule_broadcast(int(campaign_id))
    except Exception:
        # A fresh database may be in the middle of its first startup. The next
        # manually created campaign still works; do not block the whole app.
        pass


async def _broadcast_retry_scheduler() -> None:
    """Resume due broadcast recipients without waiting for a dyno restart."""
    log = logging.getLogger("amp.broadcast_retry")
    while True:
        try:
            async with job_lock(db, "broadcast_retry_scan", ttl_seconds=45) as acquired:
                if acquired:
                    now = datetime.utcnow()
                    async with db.session_factory() as session:
                        campaign_ids = list((await session.scalars(
                            select(BroadcastRecipient.campaign_id)
                            .join(BroadcastCampaign, BroadcastCampaign.id == BroadcastRecipient.campaign_id)
                            .where(
                                BroadcastCampaign.status.in_(["queued", "sending"]),
                                BroadcastRecipient.status.in_(["pending", "retry"]),
                                or_(BroadcastRecipient.next_retry_at.is_(None), BroadcastRecipient.next_retry_at <= now),
                            )
                            .distinct()
                            .limit(50)
                        )).all())
                    for campaign_id in campaign_ids:
                        _schedule_broadcast(int(campaign_id))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Помилка retry-сканера розсилок: %s", exc)
        await asyncio.sleep(60)



async def _deliver_broadcast_campaign(campaign_id: int) -> None:
    """Queue every manual broadcast recipient into the canonical Notification Center.

    Delivery itself is performed by the same retry worker as reminders, cases,
    surveys and system messages. BroadcastCampaign/BroadcastRecipient remain as
    campaign/audience history and are synchronized from Notification results.
    """
    async with job_lock(db, f"broadcast:{campaign_id}", ttl_seconds=240) as acquired:
        if not acquired:
            return
        async with db.session_factory() as session:
            campaign = await session.get(BroadcastCampaign, campaign_id)
            if not campaign or campaign.status in {"completed", "completed_with_errors", "failed"}:
                return
            campaign.status = "sending"
            campaign.started_at = campaign.started_at or datetime.utcnow()
            campaign.completed_at = None
            rows = (await session.execute(
                select(BroadcastRecipient, User)
                .join(User, User.id == BroadcastRecipient.user_id)
                .where(
                    BroadcastRecipient.campaign_id == campaign_id,
                    BroadcastRecipient.status.in_(["pending", "retry"]),
                )
                .order_by(BroadcastRecipient.id.asc())
            )).all()
            for recipient, user in rows:
                text = personalize_message(campaign.message_text, user)
                if len(text) > 4096:
                    recipient.status = "failed"
                    recipient.error_text = "Повідомлення після персоналізації перевищує 4096 символів"
                    recipient.next_retry_at = None
                    continue
                await queue_telegram_delivery(
                    session, recipient.recipient_tg_id, text,
                    source="broadcast", notification_type="broadcast", title=f"Розсилка №{campaign.id}",
                    recipient_user_id=user.id, entity_type="broadcast_recipient", entity_id=recipient.id,
                    dedupe_key=f"broadcast:{campaign.id}:recipient:{recipient.id}", parse_mode=None,
                )
                recipient.status = "pending"
                recipient.error_text = ""
                recipient.next_retry_at = None
            await session.commit()



def _clean_broadcast_text(text: str, template_code: str | None = None) -> str:
    value = (text or "").strip()
    if not value and template_code in BROADCAST_TEMPLATES:
        value = BROADCAST_TEMPLATES[template_code]["text"]
    if not value:
        raise HTTPException(status_code=400, detail="Напишіть текст повідомлення або оберіть шаблон.")
    if len(value) > 3800:
        raise HTTPException(status_code=400, detail="Повідомлення завелике. Скоротіть текст до 3800 символів.")
    return value


async def _broadcast_form_context(session, request: Request, **extra):
    settlements = [x for x in (await session.scalars(
        select(User.settlement)
        .where(User.status == UserStatus.ACTIVE.value, User.settlement.is_not(None), User.settlement != "")
        .distinct()
        .order_by(User.settlement.asc())
    )).all() if x]
    events = (await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(100))).all()
    campaigns = (await session.scalars(
        select(BroadcastCampaign).order_by(BroadcastCampaign.created_at.desc()).limit(30)
    )).all()
    custom_templates = list((await session.scalars(
        select(BroadcastTemplate).order_by(BroadcastTemplate.active.desc(), BroadcastTemplate.title.asc())
    )).all())
    available_templates = template_options() + [
        (f"custom:{item.id}", f"⭐ {item.title}", item.text)
        for item in custom_templates if item.active
    ]
    data = {
        "settlements": settlements,
        "events": events,
        "campaigns": campaigns,
        "broadcast_templates": available_templates,
        "custom_templates": custom_templates,
        "preview": None,
        "form_data": {},
    }
    data.update(extra)
    return ctx(request, **data)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/admin")


@app.get("/admin", include_in_schema=False)
async def admin_root(request: Request):
    return RedirectResponse("/admin/dashboard" if logged_in(request) else "/admin/login")


async def _audit_auth(action: str, *, actor_label: str, details: str = "", account_id: int | None = None) -> None:
    async with db.session_factory() as session:
        await log_audit(session, action, actor_label=actor_label, entity_type="web_staff_account", entity_id=account_id, details=details)
        await session.commit()


async def _send_web_2fa_code(account: WebStaffAccount, code: str) -> None:
    tg_id = account.two_factor_tg_id
    if not tg_id and account.role == "superadmin" and settings.superadmin_ids:
        tg_id = min(settings.superadmin_ids)
    if not tg_id or not settings.bot_token:
        raise HTTPException(
            status_code=503,
            detail="Для цього акаунта не налаштовано Telegram для двоетапного входу. Зверніться до суперадміністратора.",
        )
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(
            tg_id,
            "🔐 Код входу в web-панель АМП\n\n"
            f"Код: {code}\n"
            f"Дійсний {OTP_TTL_MINUTES} хв.\n\n"
            "Якщо це не ви — не передавайте код нікому та змініть пароль.",
        )
    finally:
        await bot.session.close()


async def _establish_web_session(request: Request, db_session, account: WebStaffAccount) -> None:
    raw_token = generate_session_token()
    now = datetime.utcnow()
    ua = str(request.headers.get("user-agent") or "")[:500]
    ip = client_ip(list(request.scope.get("headers") or []), request.client.host if request.client else None)
    db_session.add(WebAdminSession(
        account_id=account.id,
        token_hash=token_hash(raw_token),
        user_agent=ua,
        ip_address=ip,
        created_at=now,
        last_seen_at=now,
        expires_at=session_expiry(now),
    ))
    account.last_login_at = now
    account.failed_attempts = 0
    account.locked_until = None
    account.updated_at = now
    await log_audit(
        db_session, "web_login", actor_label=account.display_name,
        entity_type="web_staff_account", entity_id=account.id,
        details=f"Успішний вхід; {browser_label(ua)}",
    )
    await db_session.commit()

    csrf = generate_csrf_token()
    request.session.clear()
    request.session["csrf_token"] = csrf
    request.session["admin_auth"] = True
    request.session["admin_account_id"] = account.id
    request.session["admin_name"] = account.display_name
    request.session["admin_login"] = account.username
    request.session["admin_role"] = account.role
    request.session["admin_permissions"] = sorted(effective_permissions(account.role, account.permissions_json))
    request.session["admin_session_token"] = raw_token


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if logged_in(request):
        return RedirectResponse("/admin/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error=None))


@app.post("/admin/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    now = datetime.utcnow()
    async with db.session_factory() as session:
        account = await session.scalar(select(WebStaffAccount).where(WebStaffAccount.username == username))
        if not account or not account.active:
            await log_audit(session, "web_login_failed", actor_label=f"login:{username or 'порожньо'}", entity_type="web_auth", details="Невідомий або вимкнений акаунт")
            await session.commit()
            return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error="Невірний логін або пароль"), status_code=401)

        if account.locked_until and account.locked_until > now:
            await log_audit(session, "web_login_blocked", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"Блокування до {account.locked_until.isoformat()}")
            await session.commit()
            return templates.TemplateResponse(
                request=request, name="login.html",
                context=ctx(request, error=f"Вхід тимчасово заблоковано після невдалих спроб. Спробуйте після {account.locked_until.strftime('%H:%M')}"),
                status_code=429,
            )

        if not verify_password(password, account.password_hash):
            account.failed_attempts = int(account.failed_attempts or 0) + 1
            remaining = max(0, LOGIN_MAX_ATTEMPTS - account.failed_attempts)
            if account.failed_attempts >= LOGIN_MAX_ATTEMPTS:
                account.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            account.updated_at = now
            await log_audit(
                session, "web_login_failed", actor_label=account.display_name,
                entity_type="web_staff_account", entity_id=account.id,
                details=f"Невірний пароль; спроба {account.failed_attempts}/{LOGIN_MAX_ATTEMPTS}",
            )
            await session.commit()
            error = (
                f"Забагато невдалих спроб. Вхід заблоковано на {LOGIN_LOCK_MINUTES} хв."
                if account.locked_until else f"Невірний логін або пароль. Залишилось спроб: {remaining}."
            )
            return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error=error), status_code=401)

        account.failed_attempts = 0
        account.locked_until = None
        account.updated_at = now
        requires_2fa = account.role == "superadmin" or bool(account.two_factor_enabled)
        if requires_2fa:
            code = generate_otp()
            nonce = token_urlsafe(16)
            try:
                await _send_web_2fa_code(account, code)
            except HTTPException as exc:
                await log_audit(session, "web_2fa_unavailable", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=str(exc.detail))
                await session.commit()
                return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error=str(exc.detail)), status_code=503)
            await log_audit(session, "web_login_password_ok_2fa", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details="Пароль правильний; надіслано одноразовий код")
            await session.commit()
            csrf = _csrf_token(request)
            request.session.clear()
            request.session["csrf_token"] = csrf
            request.session["pending_2fa_account_id"] = account.id
            request.session["pending_2fa_nonce"] = nonce
            request.session["pending_2fa_hash"] = otp_hash(code, nonce)
            request.session["pending_2fa_expires"] = (now + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
            request.session["pending_2fa_attempts"] = 0
            return RedirectResponse("/admin/login/2fa", status_code=303)

        await _establish_web_session(request, session, account)
        target = "/admin/account/password?required=1" if account.must_change_password else "/admin/dashboard"
        return RedirectResponse(target, status_code=303)


@app.get("/admin/login/2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request):
    if not request.session.get("pending_2fa_account_id"):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request=request, name="login_2fa.html", context=ctx(request, error=None))


@app.post("/admin/login/2fa", response_class=HTMLResponse)
async def login_2fa(request: Request, code: str = Form(...)):
    account_id = request.session.get("pending_2fa_account_id")
    nonce = str(request.session.get("pending_2fa_nonce") or "")
    expected = str(request.session.get("pending_2fa_hash") or "")
    expires_raw = str(request.session.get("pending_2fa_expires") or "")
    attempts = int(request.session.get("pending_2fa_attempts") or 0)
    if not account_id or not nonce or not expected:
        return RedirectResponse("/admin/login", status_code=303)
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        expires = datetime.min
    if datetime.utcnow() > expires:
        csrf = _csrf_token(request)
        request.session.clear(); request.session["csrf_token"] = csrf
        return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error="Код двоетапного входу застарів. Увійдіть ще раз."), status_code=401)

    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id))
        if not account or not account.active:
            return RedirectResponse("/admin/login", status_code=303)
        if not verify_otp(code, nonce, expected):
            attempts += 1
            request.session["pending_2fa_attempts"] = attempts
            await log_audit(session, "web_2fa_failed", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"Невірний одноразовий код; спроба {attempts}/{OTP_MAX_ATTEMPTS}")
            await session.commit()
            if attempts >= OTP_MAX_ATTEMPTS:
                csrf = _csrf_token(request)
                request.session.clear(); request.session["csrf_token"] = csrf
                return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error="Забагато невдалих кодів двоетапного входу. Увійдіть заново."), status_code=401)
            return templates.TemplateResponse(request=request, name="login_2fa.html", context=ctx(request, error=f"Невірний код. Залишилось спроб: {OTP_MAX_ATTEMPTS-attempts}."), status_code=401)
        await log_audit(session, "web_2fa_success", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details="Двоетапний вхід підтверджено")
        await _establish_web_session(request, session, account)
        target = "/admin/account/password?required=1" if account.must_change_password else "/admin/dashboard"
        return RedirectResponse(target, status_code=303)


@app.post("/admin/logout")
async def logout(request: Request):
    raw_token = str(request.session.get("admin_session_token") or "")
    actor = request.session.get("admin_name", "web")
    account_id = request.session.get("admin_account_id")
    if raw_token:
        async with db.session_factory() as session:
            row = await session.scalar(select(WebAdminSession).where(WebAdminSession.token_hash == token_hash(raw_token)))
            if row and row.revoked_at is None:
                row.revoked_at = datetime.utcnow()
            await log_audit(session, "web_logout", actor_label=actor, entity_type="web_staff_account", entity_id=account_id, details="Сесію завершено користувачем")
            await session.commit()
    request.session.clear()
    request.session["csrf_token"] = generate_csrf_token()
    return RedirectResponse("/admin/login", status_code=303)


async def _account_security_context(request: Request, *, error: str | None = None, success: str | None = None, required: bool = False):
    account_id = request.session.get("admin_account_id")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id)) if account_id else None
        sessions = []
        if account:
            sessions = list((await session.scalars(
                select(WebAdminSession).where(
                    WebAdminSession.account_id == account.id,
                    WebAdminSession.revoked_at.is_(None),
                ).order_by(WebAdminSession.last_seen_at.desc())
            )).all())
    current_hash = token_hash(str(request.session.get("admin_session_token") or ""))
    return ctx(
        request, account=account, web_sessions=sessions, current_session_hash=current_hash,
        browser_label=browser_label, error=error, success=success, password_required=required,
    )


@app.get("/admin/account", response_class=HTMLResponse)
async def account_security(request: Request):
    if r := guard(request): return r
    context = await _account_security_context(request)
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@app.get("/admin/account/password", response_class=HTMLResponse)
async def account_password_page(request: Request, required: int = 0):
    if r := guard(request): return r
    context = await _account_security_context(request, required=bool(required))
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@app.post("/admin/account/password", response_class=HTMLResponse)
async def account_password_change(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if r := guard(request): return r
    account_id = request.session.get("admin_account_id")
    raw_token = str(request.session.get("admin_session_token") or "")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id)) if account_id else None
        if not account:
            request.session.clear()
            return RedirectResponse("/admin/login", 303)
        if not verify_password(current_password, account.password_hash):
            await log_audit(session, "web_password_change_failed", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details="Невірний поточний пароль")
            await session.commit()
            context = await _account_security_context(request, error="Поточний пароль введено неправильно.", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        if new_password != confirm_password:
            context = await _account_security_context(request, error="Новий пароль і підтвердження не збігаються.", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        errors = password_errors(new_password, username=account.username)
        if errors:
            context = await _account_security_context(request, error="Пароль не відповідає вимогам: " + ", ".join(errors) + ".", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        if verify_password(new_password, account.password_hash):
            context = await _account_security_context(request, error="Новий пароль має відрізнятися від поточного.", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        account.password_hash = hash_password(new_password)
        account.must_change_password = False
        account.password_changed_at = datetime.utcnow()
        account.updated_at = datetime.utcnow()
        # Password change invalidates all other devices, while the current one stays active.
        current_hash = token_hash(raw_token)
        other_sessions = (await session.scalars(select(WebAdminSession).where(
            WebAdminSession.account_id == account.id,
            WebAdminSession.revoked_at.is_(None),
            WebAdminSession.token_hash != current_hash,
        ))).all()
        for row in other_sessions:
            row.revoked_at = datetime.utcnow()
        await log_audit(session, "web_password_changed", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"Пароль змінено; завершено інших сесій: {len(other_sessions)}")
        await session.commit()
    context = await _account_security_context(request, success="Пароль успішно змінено. Інші активні сесії завершено.")
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@app.post("/admin/account/2fa", response_class=HTMLResponse)
async def account_2fa_update(request: Request, enabled: str = Form(""), telegram_id: str = Form("")):
    if r := guard(request): return r
    account_id = request.session.get("admin_account_id")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id)) if account_id else None
        if not account:
            return RedirectResponse("/admin/login", 303)
        want_enabled = bool(enabled) or account.role == "superadmin"
        tg_id = None
        if telegram_id.strip():
            try:
                tg_id = int(telegram_id.strip())
            except ValueError:
                context = await _account_security_context(request, error="Telegram ID має бути числом.")
                return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        if want_enabled and not tg_id:
            tg_id = account.two_factor_tg_id or (min(settings.superadmin_ids) if account.role == "superadmin" and settings.superadmin_ids else None)
        if want_enabled and not tg_id:
            context = await _account_security_context(request, error="Для двоетапного входу потрібно вказати ідентифікатор Telegram.")
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        account.two_factor_enabled = want_enabled
        account.two_factor_tg_id = tg_id if want_enabled else None
        account.updated_at = datetime.utcnow()
        await log_audit(session, "web_2fa_settings", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"enabled={account.two_factor_enabled}; telegram_id={'set' if account.two_factor_tg_id else 'none'}")
        await session.commit()
    context = await _account_security_context(request, success="Налаштування двоетапного входу збережено.")
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@app.post("/admin/account/sessions/{session_id}/revoke")
async def account_session_revoke(request: Request, session_id: int):
    if r := guard(request): return r
    account_id = int(request.session.get("admin_account_id") or 0)
    raw_token = str(request.session.get("admin_session_token") or "")
    async with db.session_factory() as session:
        row = await session.get(WebAdminSession, session_id)
        if not row or row.account_id != account_id:
            raise HTTPException(status_code=404, detail="Сесію не знайдено")
        row.revoked_at = datetime.utcnow()
        await log_audit(session, "web_session_revoked", actor_label=request.session.get("admin_name", "web"), entity_type="web_admin_session", entity_id=row.id, details="Сесію завершено з профілю")
        await session.commit()
        is_current = row.token_hash == token_hash(raw_token)
    if is_current:
        request.session.clear(); request.session["csrf_token"] = generate_csrf_token()
        return RedirectResponse("/admin/login", 303)
    return RedirectResponse("/admin/account", 303)


async def _security_accounts_context(request: Request, *, temp_password: str | None = None, temp_username: str | None = None, success: str | None = None):
    async with db.session_factory() as session:
        accounts = list((await session.scalars(select(WebStaffAccount).order_by(WebStaffAccount.role.desc(), WebStaffAccount.display_name.asc()))).all())
        active_counts = {}
        for account in accounts:
            active_counts[account.id] = int(await session.scalar(select(func.count(WebAdminSession.id)).where(
                WebAdminSession.account_id == account.id,
                WebAdminSession.revoked_at.is_(None),
                or_(WebAdminSession.expires_at.is_(None), WebAdminSession.expires_at > datetime.utcnow()),
            )) or 0)
        telegram_staff = list((await session.scalars(
            select(User).where(User.role.in_([UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value]))
            .order_by(User.role.desc(), User.full_name.asc())
        )).all())
    return ctx(
        request, staff_accounts=accounts, telegram_staff=telegram_staff, active_session_counts=active_counts,
        permission_groups=PERMISSION_GROUPS, effective_permissions=effective_permissions,
        temp_password=temp_password, temp_username=temp_username, success=success, now=datetime.utcnow(),
    )


@app.get("/admin/security", response_class=HTMLResponse)
async def security_accounts(request: Request):
    if r := guard_superadmin(request): return r
    return templates.TemplateResponse(request=request, name="security_accounts.html", context=await _security_accounts_context(request))


@app.post("/admin/security/accounts/{account_id}/permissions")
async def security_account_permissions(request: Request, account_id: int):
    if r := guard_superadmin(request): return r
    form = await request.form()
    selected = [str(value) for value in form.getlist("permissions")]
    mode = str(form.get("mode") or "custom")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Акаунт не знайдено")
        if account.role == UserRole.SUPERADMIN.value:
            account.permissions_json = None
            note = "Суперадміністратор: повний доступ незмінний"
        elif mode == "inherit":
            account.permissions_json = None
            note = "права=налаштування_ролі"
        else:
            account.permissions_json = dump_permissions(selected)
            note = f"права={account.permissions_json}"
        account.updated_at = datetime.utcnow()
        await log_audit(session, "web_permissions_update", actor_label=request.session.get("admin_name", "web"), entity_type="web_staff_account", entity_id=account.id, details=note)
        await session.commit()
    return RedirectResponse("/admin/security", 303)


@app.post("/admin/security/telegram/{user_id}/permissions")
async def security_telegram_permissions(request: Request, user_id: int):
    if r := guard_superadmin(request): return r
    form = await request.form()
    selected = [str(value) for value in form.getlist("permissions")]
    mode = str(form.get("mode") or "custom")
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user or user.role not in {UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
            raise HTTPException(status_code=404, detail="Працівника не знайдено")
        if user.role == UserRole.SUPERADMIN.value:
            user.staff_permissions_json = None
            note = "Суперадміністратор: повний доступ незмінний"
        elif mode == "inherit":
            user.staff_permissions_json = None
            note = "права=налаштування_ролі"
        else:
            user.staff_permissions_json = dump_permissions(selected)
            note = f"права={user.staff_permissions_json}"
        await log_audit(session, "telegram_permissions_update", actor_label=request.session.get("admin_name", "web"), entity_type="user", entity_id=user.id, details=note)
        await session.commit()
    return RedirectResponse("/admin/security", 303)


@app.post("/admin/security/accounts/{account_id}/reset-password", response_class=HTMLResponse)
async def security_reset_password(request: Request, account_id: int):
    if r := guard_superadmin(request): return r
    temp_password = generate_temporary_password()
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Акаунт не знайдено")
        account.password_hash = hash_password(temp_password)
        account.must_change_password = True
        account.failed_attempts = 0
        account.locked_until = None
        account.password_changed_at = datetime.utcnow()
        account.updated_at = datetime.utcnow()
        rows = (await session.scalars(select(WebAdminSession).where(WebAdminSession.account_id == account.id, WebAdminSession.revoked_at.is_(None)))).all()
        for row in rows:
            row.revoked_at = datetime.utcnow()
        await log_audit(session, "web_password_reset", actor_label=request.session.get("admin_name", "web"), entity_type="web_staff_account", entity_id=account.id, details=f"Створено тимчасовий пароль; завершено сесій: {len(rows)}")
        await session.commit()
        username = account.username
    context = await _security_accounts_context(request, temp_password=temp_password, temp_username=username, success="Тимчасовий пароль створено. Покажіть його користувачу один раз безпечним каналом.")
    return templates.TemplateResponse(request=request, name="security_accounts.html", context=context)


@app.post("/admin/security/accounts/{account_id}/sessions/revoke-all")
async def security_revoke_all_sessions(request: Request, account_id: int):
    if r := guard_superadmin(request): return r
    current_account_id = int(request.session.get("admin_account_id") or 0)
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Акаунт не знайдено")
        rows = (await session.scalars(select(WebAdminSession).where(WebAdminSession.account_id == account.id, WebAdminSession.revoked_at.is_(None)))).all()
        for row in rows:
            row.revoked_at = datetime.utcnow()
        await log_audit(session, "web_sessions_revoke_all", actor_label=request.session.get("admin_name", "web"), entity_type="web_staff_account", entity_id=account.id, details=f"Завершено сесій: {len(rows)}")
        await session.commit()
    if account_id == current_account_id:
        request.session.clear(); request.session["csrf_token"] = generate_csrf_token()
        return RedirectResponse("/admin/login", 303)
    return RedirectResponse("/admin/security", 303)

# v1.7.4: route groups are kept in focused modules.  The auth/security/bootstrap
# layer stays here while feature routes live under app.web.routes.
from .routes import (
    dashboard as dashboard_routes, gamification as gamification_routes,
    analytics as analytics_routes, reports as reports_routes, surveys as surveys_routes,
    opportunities as opportunities_routes, users as users_routes, events as events_routes,
    quests as quests_routes, activities as activities_routes, tasks as tasks_routes,
    ideas as ideas_routes, requests as requests_routes, broadcasts as broadcasts_routes,
    system as system_routes, adminux as adminux_routes, notifications as notifications_routes, donations as donations_routes,
)

for _router_module in (
    dashboard_routes, gamification_routes, analytics_routes, reports_routes, surveys_routes,
    opportunities_routes, users_routes, events_routes, quests_routes, activities_routes,
    tasks_routes, ideas_routes, requests_routes, broadcasts_routes, system_routes, adminux_routes, notifications_routes, donations_routes,
):
    app.include_router(_router_module.router)
