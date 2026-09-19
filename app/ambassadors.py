from __future__ import annotations

from .model_domains.base import UserRole

AMP_TEAM_ROLES: tuple[str, ...] = (
    UserRole.AMBASSADOR.value,
    UserRole.COORDINATOR.value,
    UserRole.ADMIN.value,
    UserRole.SUPERADMIN.value,
)

AMBASSADOR_RESPONSIBILITIES: tuple[str, ...] = (
    "Спортзал",
    "Івент-зал",
    "Бібліотека",
    "Подкаст-студія",
    "Музична кімната",
    "Настільні ігри",
    "Кухня",
    "Внутрішній дворик",
)


def is_amp_team_role(role: str | None) -> bool:
    return (role or "") in AMP_TEAM_ROLES


def responsibility_label(value: str | None) -> str:
    clean = (value or "").strip()
    return clean if clean in AMBASSADOR_RESPONSIBILITIES else "Не визначено"
