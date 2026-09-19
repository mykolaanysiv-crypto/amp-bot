from __future__ import annotations

from .time_utils import clock

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Iterable

PASSWORD_ITERATIONS = 310_000
PASSWORD_ALGO = "pbkdf2_sha256"
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15
WEB_SESSION_DAYS = 30
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

PUBLIC_MEDIA_CATEGORIES = frozenset({
    "events", "quests", "opportunities", "badges", "ambassador_badges",
    "rewards", "giveaway_prizes", "survey_questions", "goals", "tasks", "donation_reports",
})
PARTICIPANT_PRIVATE_MEDIA_CATEGORIES = frozenset({"activity_results", "qr_badges"})
STAFF_PRIVATE_MEDIA_CATEGORIES = frozenset({"requests", "ideas", "moderation", "event_registration_templates", "ambassador_reports", "team_task_reports", "giveaway_proofs"})
SUPERADMIN_PRIVATE_MEDIA_CATEGORIES = frozenset({"consents", "sensitive_documents", "admin_documents"})


def media_access_level(category: str | None) -> str:
    value = (category or "").strip().lower()
    if value in PUBLIC_MEDIA_CATEGORIES:
        return "public"
    if value in PARTICIPANT_PRIVATE_MEDIA_CATEGORIES:
        return "participant_private"
    if value in SUPERADMIN_PRIVATE_MEDIA_CATEGORIES:
        return "superadmin_private"
    if value in STAFF_PRIVATE_MEDIA_CATEGORIES:
        return "staff_private"
    # Secure-by-default: a new category is private until explicitly classified.
    return "staff_private"


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_ALGO}${iterations}${base64.urlsafe_b64encode(salt).decode().rstrip('=')}${base64.urlsafe_b64encode(digest).decode().rstrip('=')}"


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if algo != PASSWORD_ALGO:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def password_errors(password: str, *, username: str = "") -> list[str]:
    value = password or ""
    errors: list[str] = []
    if len(value) < 12:
        errors.append("щонайменше 12 символів")
    if not any(ch.islower() for ch in value):
        errors.append("маленька літера")
    if not any(ch.isupper() for ch in value):
        errors.append("велика літера")
    if not any(ch.isdigit() for ch in value):
        errors.append("цифра")
    if not any(not ch.isalnum() for ch in value):
        errors.append("спецсимвол")
    if username and username.lower() in value.lower():
        errors.append("пароль не повинен містити логін")
    return errors


def generate_temporary_password() -> str:
    # Guaranteed to satisfy the policy while remaining random.
    return f"Amp!{secrets.token_urlsafe(13)}9aA"


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_hash(code: str, nonce: str) -> str:
    return hashlib.sha256(f"{nonce}:{code}".encode("utf-8")).hexdigest()


def verify_otp(code: str, nonce: str, expected_hash: str) -> bool:
    return hmac.compare_digest(otp_hash((code or "").strip(), nonce), expected_hash or "")


def session_expiry(now: datetime | None = None) -> datetime:
    return (now or clock.storage_utc()) + timedelta(days=WEB_SESSION_DAYS)


def browser_label(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    browser = "Браузер"
    if "edg/" in ua:
        browser = "Microsoft Edge"
    elif "chrome/" in ua and "chromium" not in ua:
        browser = "Google Chrome"
    elif "firefox/" in ua:
        browser = "Mozilla Firefox"
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "Safari"
    elif "opera" in ua or "opr/" in ua:
        browser = "Opera"
    platform = ""
    if "iphone" in ua or "ipad" in ua:
        platform = "iOS"
    elif "android" in ua:
        platform = "Android"
    elif "macintosh" in ua or "mac os x" in ua:
        platform = "macOS"
    elif "windows" in ua:
        platform = "Windows"
    elif "linux" in ua:
        platform = "Linux"
    return f"{browser} • {platform}" if platform else browser


def client_ip(headers: Iterable[tuple[bytes, bytes]], client_host: str | None = None) -> str:
    for key, value in headers:
        if key.lower() == b"x-forwarded-for":
            return value.decode("latin1").split(",", 1)[0].strip()[:96]
    return (client_host or "")[:96]
