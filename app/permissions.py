from __future__ import annotations

import json
from collections import OrderedDict
from typing import Iterable

from .models import UserRole

# v1.10.2: permissions are intentionally explicit strings.  They are stored as
# JSON arrays so new permissions can be introduced additively without schema
# migrations.  Superadmin is an unconditional break-glass role and always has
# every permission.
PERMISSION_GROUPS: "OrderedDict[str, tuple[tuple[str, str], ...]]" = OrderedDict([
    ("Учасники", (
        ("participants.view", "Перегляд"),
        ("participants.edit", "Редагування"),
        ("participants.approve", "Підтвердження / активація"),
    )),
    ("Події", (
        ("events.create", "Створення"),
        ("events.edit", "Редагування / attendance / scanner"),
        ("events.delete", "Видалення / скасування"),
    )),
    ("Активності", (
        ("quests.manage", "Квести"),
        ("volunteer.manage", "Волонтерство"),
        ("activities.manage", "Активності"),
        ("opportunities.manage", "Можливості"),
        ("surveys.manage", "Опитування"),
        ("ideas.manage", "Ідеї"),
        ("cases.manage", "Звернення / кейси"),
    )),
    ("XP та гейміфікація", (
        ("xp.award", "Нарахування XP"),
        ("gamification.manage", "Бейджі / винагороди / сезони / цілі"),
    )),
    ("Дані та комунікація", (
        ("analytics.view", "Аналітика"),
        ("reports.basic_export", "Базові звіти / експорт"),
        ("reports.sensitive_export", "Sensitive export"),
        ("broadcast.send", "Розсилки"),
        ("notifications.manage", "Центр сповіщень"),
    )),
    ("Контроль та система", (
        ("moderation.manage", "Модерація"),
        ("system.health", "Стан системи"),
        ("audit.view", "Аудит"),
        ("settings.manage", "Налаштування правил"),
        ("security.manage", "Безпека та права доступу"),
    )),
])

ALL_PERMISSIONS = frozenset(code for rows in PERMISSION_GROUPS.values() for code, _ in rows)

# Preserve the access people had before v1.10.2 when no explicit permission set
# has been saved yet.  Once a superadmin saves a custom set, that set becomes the
# source of truth.
ROLE_DEFAULTS = {
    UserRole.COORDINATOR.value: frozenset({
        "events.create", "events.edit",
        "quests.manage", "volunteer.manage", "activities.manage", "opportunities.manage",
        "xp.award", "gamification.manage", "system.health",
    }),
    UserRole.ADMIN.value: frozenset({
        "participants.view", "participants.edit", "participants.approve",
        "events.create", "events.edit", "events.delete",
        "quests.manage", "volunteer.manage", "activities.manage", "opportunities.manage", "surveys.manage",
        "ideas.manage", "cases.manage", "xp.award", "gamification.manage",
        "analytics.view", "reports.basic_export", "notifications.manage", "system.health",
    }),
    UserRole.SUPERADMIN.value: ALL_PERMISSIONS,
}


def parse_permissions(raw: str | None) -> frozenset[str] | None:
    """Return None for legacy/unconfigured rows, otherwise a validated set."""
    if raw is None or not str(raw).strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        # An explicit but malformed ACL must fail closed instead of silently
        # falling back to the broader role defaults.
        return frozenset()
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item) for item in value if str(item) in ALL_PERMISSIONS)


def dump_permissions(values: Iterable[str]) -> str:
    clean = sorted({str(value) for value in values if str(value) in ALL_PERMISSIONS})
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def effective_permissions(role: str | None, raw: str | None = None) -> frozenset[str]:
    role = str(role or "")
    if role == UserRole.SUPERADMIN.value:
        return ALL_PERMISSIONS
    explicit = parse_permissions(raw)
    if explicit is not None:
        return explicit
    return ROLE_DEFAULTS.get(role, frozenset())


def has_permission(role: str | None, raw: str | None, permission: str) -> bool:
    return permission in effective_permissions(role, raw)


def any_permission(role: str | None, raw: str | None, *permissions: str) -> bool:
    current = effective_permissions(role, raw)
    return any(permission in current for permission in permissions)


def required_web_permission(path: str, method: str) -> str | None:
    """Central safety net for the most security-sensitive web capabilities.

    Individual routes may still apply stricter checks.  This mapping prevents a
    stale direct URL or crafted POST from bypassing the UI permission controls.
    """
    method = (method or "GET").upper()
    path = str(path or "")

    if path.startswith("/admin/security"):
        return "security.manage"
    if path.startswith("/admin/moderation"):
        return "moderation.manage"
    if path.startswith("/admin/broadcasts"):
        return "broadcast.send"
    if path.startswith("/admin/notifications"):
        return "notifications.manage"
    if path.startswith("/admin/settings"):
        return "settings.manage"
    if path.startswith("/admin/audit"):
        return "audit.view"
    if path.startswith("/admin/system-health"):
        return "system.health"
    if path.startswith("/admin/analytics"):
        return "analytics.view"
    if path.startswith("/admin/reports"):
        return "reports.basic_export"
    if path == "/admin/export/sensitive":
        return "reports.sensitive_export"
    if path == "/admin/export":
        return "reports.basic_export"

    if path.startswith("/admin/users"):
        if path.endswith("/xp") and method == "POST":
            return "xp.award"
        if "/status-request/" in path or "/restoration/" in path or path.endswith("/activate"):
            return "participants.approve"
        if path.endswith("/ban") or path.endswith("/unban"):
            return "moderation.manage"
        if method == "GET":
            return "participants.view"
        return "participants.edit"

    if path.startswith("/admin/events"):
        if method == "GET":
            if "participants-sensitive" in path:
                return "reports.sensitive_export"
            if "participants." in path or path.endswith("/registration-form"):
                return "reports.basic_export"
            return None
        if path.endswith("/create"):
            return "events.create"
        if path.endswith("/delete") or path.endswith("/cancel"):
            return "events.delete"
        return "events.edit"

    if path.startswith("/admin/quests"):
        return "quests.manage" if method != "GET" else None
    if path.startswith("/admin/tasks"):
        return "volunteer.manage" if method != "GET" else None
    if path.startswith("/admin/activities"):
        return "activities.manage" if method != "GET" else None
    if path.startswith("/admin/opportunities"):
        return "opportunities.manage" if method != "GET" else None
    if path.startswith("/admin/surveys"):
        return "surveys.manage" if method != "GET" else None
    if path.startswith("/admin/ideas"):
        return "ideas.manage" if method != "GET" else None
    if path.startswith("/admin/requests"):
        return "cases.manage" if method != "GET" else None
    if any(path.startswith(prefix) for prefix in ("/admin/goals", "/admin/badges", "/admin/rewards", "/admin/seasons", "/admin/streaks")):
        return "gamification.manage" if method != "GET" else None
    return None


def required_web_any_permissions(path: str, method: str) -> tuple[str, ...]:
    """Permissions where *any one* grants read/navigation access.

    v1.10.2 keeps action permissions granular (for example events.create/edit/delete)
    without introducing a second events.view flag.  This helper closes the direct-URL
    gap: hiding a sidebar link is not considered access control.
    """
    method = (method or "GET").upper()
    path = str(path or "")
    if method != "GET":
        return ()

    if path.startswith("/admin/events"):
        # Sensitive/basic exports are handled by required_web_permission first.
        return ("events.create", "events.edit", "events.delete")
    if path.startswith("/admin/quests"):
        return ("quests.manage",)
    if path.startswith("/admin/tasks"):
        return ("volunteer.manage",)
    if path.startswith("/admin/activities"):
        return ("activities.manage",)
    if path.startswith("/admin/opportunities"):
        return ("opportunities.manage",)
    if path.startswith("/admin/surveys"):
        return ("surveys.manage",)
    if path.startswith("/admin/ideas"):
        return ("ideas.manage",)
    if path.startswith("/admin/requests"):
        return ("cases.manage",)
    if path.startswith("/admin/leaderboard") or path.startswith("/admin/streaks"):
        return ("gamification.manage", "xp.award")
    if any(path.startswith(prefix) for prefix in ("/admin/goals", "/admin/badges", "/admin/rewards", "/admin/seasons")):
        return ("gamification.manage",)
    if path.startswith("/admin/calendar"):
        return (
            "events.create", "events.edit", "events.delete", "quests.manage",
            "volunteer.manage", "surveys.manage", "opportunities.manage",
            "cases.manage", "ideas.manage", "gamification.manage",
        )
    return ()
