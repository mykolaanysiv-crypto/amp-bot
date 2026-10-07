from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import func, or_, select

from .model_domains import AuditLog, WebAdminSession, WebAuthnCredential, WebStaffAccount
from .observability_snapshot import build_observability_snapshot
from .time_utils import clock

SENSITIVE_EXPORT_ACTIONS = {
    "web_export_sensitive",
    "web_event_participants_export_sensitive",
    "web_event_donor_register_export_sensitive",
    "web_event_standard_register_export_sensitive",
}
SENSITIVE_MEDIA_ACTIONS = {"web_sensitive_media_view", "web_sensitive_media_download"}
PERMISSION_ACTIONS = {"web_permissions_update", "telegram_permissions_update"}
CRITICAL_SECURITY_ACTIONS = {
    "web_login_failed", "web_login_blocked", "web_2fa_failed", "web_2fa_unavailable",
    "web_passkey_auth_failed", "web_passkey_register_failed", "web_password_reset",
    "web_sessions_revoke_all", "web_passkey_revoked",
}


async def build_security_center_snapshot(session, db, settings) -> dict[str, object]:
    now = clock.storage_utc()
    cutoff_24h = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(minutes=30)

    failed_login_24h = int(await session.scalar(select(func.count(AuditLog.id)).where(
        AuditLog.action == "web_login_failed", AuditLog.created_at >= cutoff_24h
    )) or 0)
    failed_mfa_24h = int(await session.scalar(select(func.count(AuditLog.id)).where(
        AuditLog.action.in_(["web_2fa_failed", "web_passkey_auth_failed"]), AuditLog.created_at >= cutoff_24h
    )) or 0)
    locked_accounts = int(await session.scalar(select(func.count(WebStaffAccount.id)).where(
        WebStaffAccount.active.is_(True), WebStaffAccount.locked_until.is_not(None), WebStaffAccount.locked_until > now
    )) or 0)
    active_sessions = int(await session.scalar(select(func.count(WebAdminSession.id)).where(
        WebAdminSession.revoked_at.is_(None),
        or_(WebAdminSession.expires_at.is_(None), WebAdminSession.expires_at > now),
    )) or 0)
    stale_sessions = int(await session.scalar(select(func.count(WebAdminSession.id)).where(
        WebAdminSession.revoked_at.is_(None),
        WebAdminSession.last_seen_at < stale_cutoff,
        or_(WebAdminSession.expires_at.is_(None), WebAdminSession.expires_at > now),
    )) or 0)
    staff_count = int(await session.scalar(select(func.count(WebStaffAccount.id)).where(WebStaffAccount.active.is_(True))) or 0)
    passkey_accounts = int(await session.scalar(select(func.count(func.distinct(WebAuthnCredential.account_id))).where(
        WebAuthnCredential.revoked_at.is_(None)
    )) or 0)
    telegram_2fa_accounts = int(await session.scalar(select(func.count(WebStaffAccount.id)).where(
        WebStaffAccount.active.is_(True),
        or_(WebStaffAccount.two_factor_enabled.is_(True), WebStaffAccount.role == "superadmin"),
    )) or 0)

    async def recent_actions(actions: set[str], limit: int = 20):
        return list((await session.scalars(select(AuditLog).where(
            AuditLog.action.in_(sorted(actions))
        ).order_by(AuditLog.created_at.desc()).limit(limit))).all())

    sensitive_exports = await recent_actions(SENSITIVE_EXPORT_ACTIONS)
    sensitive_media = await recent_actions(SENSITIVE_MEDIA_ACTIONS)
    permission_changes = await recent_actions(PERMISSION_ACTIONS)
    critical_events = await recent_actions(CRITICAL_SECURITY_ACTIONS)

    telemetry = await build_observability_snapshot(session, db, settings)
    key_configured = bool(os.getenv("FIELD_ENCRYPTION_KEY", "").strip())
    session_secret = os.getenv("WEB_SESSION_SECRET", "").strip()
    encryption_secret = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    previous_keys = bool(os.getenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", "").strip())

    warnings: list[dict[str, str]] = []
    if locked_accounts:
        warnings.append({"severity": "high", "title": "Є тимчасово заблоковані staff-акаунти", "detail": str(locked_accounts)})
    if failed_login_24h >= 5:
        warnings.append({"severity": "high", "title": "Підвищена кількість невдалих входів", "detail": f"{failed_login_24h} за 24 год"})
    if not settings.webauthn_enabled:
        warnings.append({"severity": "medium", "title": "Passkeys не активовані для цього deployment", "detail": "Налаштуйте HTTPS WEBAUTHN_ORIGIN/PUBLIC_BASE_URL"})
    elif staff_count and passkey_accounts < staff_count:
        warnings.append({"severity": "medium", "title": "Не всі staff-акаунти мають passkey", "detail": f"{passkey_accounts}/{staff_count}"})
    if not key_configured and os.getenv("DYNO"):
        warnings.append({"severity": "critical", "title": "FIELD_ENCRYPTION_KEY не налаштований", "detail": "Production encryption root secret відсутній"})
    if encryption_secret and session_secret and encryption_secret == session_secret:
        warnings.append({"severity": "critical", "title": "Ключ шифрування збігається з session secret", "detail": "Секрети мають бути розділені"})
    if telemetry["backup"].get("status") not in {"ok", "warning"}:
        warnings.append({"severity": "critical", "title": "Verified backup потребує уваги", "detail": str(telemetry["backup"].get("status"))})
    pool = telemetry["pool"]
    if isinstance(pool.get("utilization_pct"), (int, float)) and float(pool["utilization_pct"]) >= 80:
        warnings.append({"severity": "high", "title": "Високе використання DB pool", "detail": f"{pool['utilization_pct']}%"})

    return {
        "now": now,
        "summary": {
            "failed_login_24h": failed_login_24h,
            "failed_mfa_24h": failed_mfa_24h,
            "locked_accounts": locked_accounts,
            "active_sessions": active_sessions,
            "stale_sessions": stale_sessions,
            "staff_accounts": staff_count,
            "passkey_accounts": passkey_accounts,
            "telegram_2fa_accounts": telegram_2fa_accounts,
        },
        "encryption": {
            "field_key_configured": key_configured,
            "field_key_separate": bool(encryption_secret and encryption_secret != session_secret),
            "previous_keys_configured": previous_keys,
        },
        "passkeys": {
            "enabled": bool(settings.webauthn_enabled),
            "rp_id_configured": bool(settings.webauthn_rp_id),
            "https_origin": str(settings.webauthn_origin).startswith("https://"),
        },
        "sensitive_exports": sensitive_exports,
        "sensitive_media": sensitive_media,
        "permission_changes": permission_changes,
        "critical_events": critical_events,
        "warnings": warnings,
        "telemetry": telemetry,
    }
