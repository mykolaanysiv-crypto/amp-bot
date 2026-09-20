from __future__ import annotations

from ..time_utils import clock

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
from ..observability import RequestContextMiddleware, log_extra
from ..db import Database
from ..gamification import AUTOMATIC_XP_GUIDE, get_level, normalize_event_xp, normalize_manual_xp, normalize_quest_xp, normalize_task_xp
from ..model_domains import (
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
from ..analytics_modules import METRIC_META, analytics_bot_text, analytics_excel, analytics_pdf, analytics_png, build_analytics
from ..reporting import build_period_report, report_excel, report_pdf, resolve_report_period
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
from ..domain_services import (
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


# --- web request/auth/storage dependencies split from app.py in v1.13.0 ---

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
    except Exception as exc:
        logging.getLogger("amp.web_notifications").exception(
            "Не вдалося поставити Telegram-повідомлення в чергу",
            extra=log_extra("WEB_NOTIFICATION_QUEUE_FAILED", exception_type=type(exc).__name__),
        )
