from __future__ import annotations

from datetime import datetime, timedelta
import logging
from io import BytesIO
from urllib.parse import parse_qs, quote, urlparse
import re

import qrcode
from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from ..config import Settings
from ..observability import log_extra
from ..db import Database
from ..gamification import get_level, normalize_event_xp, normalize_manual_xp, normalize_quest_xp, normalize_task_xp
from ..analytics_modules import analytics_bot_text, build_analytics
from ..reliability import queue_telegram_delivery
from ..opportunity_matching import refresh_matches_for_opportunity
from ..keyboards import ADMIN_ROLES, admin_menu, admin_section_menu, compact_button_text, main_menu, pending_user_keyboard
from ..permissions import effective_permissions, has_permission
from ..model_domains import (
    ActivityApplication,
    ActivityType,
    BanRecord,
    Badge,
    ConsentHistory,
    Event,
    EventRegistration,
    Opportunity,
    Quest,
    QuestParticipation,
    Reward,
    RewardClaim,
    User,
    UserBadge,
    UserRole,
    UserStatus,
    VolunteerTask,
    VolunteerTaskParticipation,
)
from ..domain_services import (
    add_active_users_to_default_team,
    add_xp,
    complete_activity_application,
    confirm_event_attendance,
    event_checkin_window,
    admin_scan_event_participant,
    create_event,
    evaluate_automatic_badges,
    export_excel,
    get_user,
    get_user_by_tg,
    log_audit,
    reward_referral_if_ready,
    xp_total,
)
from ..ui_labels import activity_status_label, label
from ..states import (
    AdminBadgeAwardState,
    AdminBanState,
    AdminBroadcastState,
    AdminEventState,
    AdminEventScannerState,
    AdminOpportunityState,
    AdminQuestState,
    AdminRewardState,
    AdminTaskState,
    AdminXPState,
)

router = Router(name="admin")


def _single_button(text: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=compact_button_text(text), callback_data=data)]]
    )


def _two_buttons(text1: str, data1: str, text2: str, data2: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=compact_button_text(text1), callback_data=data1)
    builder.button(text=compact_button_text(text2), callback_data=data2)
    builder.adjust(1)
    return builder.as_markup()


def _callback_permission(data: str | None) -> str | None:
    value = str(data or "")
    rules = (
        (("admin:pending", "admin:consent:", "admin:approve:"), "participants.approve"),
        (("admin:block:", "admin:moderation", "admin:ban_"), "moderation.manage"),
        (("admin:add_xp",), "xp.award"),
        (("admin:create_event",), "events.create"),
        (("admin:event_scanner", "admin:event_qr", "admin:event_share", "admin:attendance", "admin:confirm_event:"), "events.edit"),
        (("admin:create_quest", "admin:quest_approvals", "admin:approve_quest:"), "quests.manage"),
        (("admin:award_badge", "admin:create_reward", "admin:reward_claims", "admin:fulfill_reward:", "admin:reject_reward:"), "gamification.manage"),
        (("admin:activity_",), "activities.manage"),
        (("admin:create_task", "admin:task_approvals", "admin:approve_task_part:"), "volunteer.manage"),
        (("admin:create_opportunity",), "opportunities.manage"),
        (("admin:analytics",), "analytics.view"),
        (("admin:export",), "reports.basic_export"),
        (("admin:broadcast",), "broadcast.send"),
    )
    for prefixes, permission in rules:
        if any(value.startswith(prefix) for prefix in prefixes):
            return permission
    return None


class AdminCallbackPermissionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        permission = _callback_permission(getattr(event, "data", None))
        if permission:
            db = data.get("db")
            if db is not None:
                async with db.session_factory() as session:
                    user = await get_user_by_tg(session, event.from_user.id)
                    allowed = bool(
                        user and user.status == UserStatus.ACTIVE.value and user.role in ADMIN_ROLES
                        and has_permission(user.role, user.staff_permissions_json, permission)
                    )
                if not allowed:
                    await event.answer("Недостатньо прав для цієї дії", show_alert=True)
                    return None
        return await handler(event, data)


router.callback_query.outer_middleware(AdminCallbackPermissionMiddleware())


async def _queue_new_entity_notice(session, text: str, source: str, dedupe_prefix: str) -> int:
    users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value, User.tg_id.is_not(None)))).all())
    for user in users:
        await queue_telegram_delivery(session,user.tg_id,text,source=source,dedupe_key=f"{dedupe_prefix}:{user.id}")
    return len(users)




async def _queue_user_notice(
    session, user: User | None, text: str, *, source: str = "admin", title: str | None = None,
    entity_type: str | None = None, entity_id: int | None = None, dedupe_key: str | None = None,
) -> None:
    """Send participant-facing admin notifications through v1.9 Notification Center."""
    if not user or not user.tg_id:
        return
    await queue_telegram_delivery(
        session, user.tg_id, text, source=source, title=title, recipient_user_id=user.id,
        entity_type=entity_type, entity_id=entity_id, dedupe_key=dedupe_key, parse_mode="HTML",
    )

async def _admin(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role not in ADMIN_ROLES:
        return None
    return user


def _staff_permissions(user: User) -> frozenset[str]:
    return effective_permissions(user.role, user.staff_permissions_json)


async def _require_permission(target: Message | CallbackQuery, db: Database, permission: str) -> User | None:
    async with db.session_factory() as session:
        admin = await _admin(session, target.from_user.id)
        allowed = bool(admin and has_permission(admin.role, admin.staff_permissions_json, permission))
    if not allowed:
        if isinstance(target, CallbackQuery):
            await target.answer("Недостатньо прав для цієї дії", show_alert=True)
        else:
            await target.answer("⛔ Недостатньо прав для цієї дії.")
        return None
    return admin


async def _full_admin(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        return None
    return user


async def _super_admin(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role != UserRole.SUPERADMIN.value:
        return None
    return user

async def _require_admin(target: Message | CallbackQuery, db: Database) -> User | None:
    async with db.session_factory() as session:
        admin = await _admin(session, target.from_user.id)
    if not admin:
        if isinstance(target, CallbackQuery):
            await target.answer("Недостатньо прав", show_alert=True)
        else:
            await target.answer("⛔ Недостатньо прав.")
    return admin



# Export compatibility helpers, including private names, to split modules.
__all__ = [name for name in globals() if not name.startswith("__")]
