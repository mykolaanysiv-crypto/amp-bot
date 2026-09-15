from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import os
import shutil
import json
from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            pass
    return result




def _parse_staff_accounts(raw: str | None) -> dict[str, dict[str, str]]:
    """Parse optional named web staff accounts from JSON.

    Example:
    {"ivan":{"password":"...","display_name":"Іван","role":"admin"}}
    Only the admin role is accepted here; the legacy WEB_ADMIN account remains
    the sole web superadmin credential.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for username, cfg in data.items():
        if not isinstance(username, str) or not isinstance(cfg, dict):
            continue
        password = str(cfg.get("password") or "").strip()
        if not password:
            continue
        result[username.strip()] = {
            "password": password,
            "display_name": str(cfg.get("display_name") or username).strip(),
            "role": "admin",
        }
    return result


def _parse_date(raw: str | None, fallback: date) -> date:
    if not raw:
        return fallback
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return fallback


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} має бути цілим числом") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} має бути в межах {minimum}..{maximum}")
    return value


def _data_dir() -> Path:
    """Version-independent storage for local use and temporary server files.

    Local installs keep SQLite/uploads in ~/AMP_Bot_Data. On Heroku the dyno
    filesystem is ephemeral, so production uses PostgreSQL plus database media
    storage; /tmp is used only for temporary/legacy compatibility files.
    """
    raw = os.getenv("AMP_DATA_DIR", "").strip()
    if raw:
        root = Path(raw).expanduser()
    elif os.getenv("DYNO"):
        root = Path("/tmp/amp_bot_data")
    else:
        root = Path.home() / "AMP_Bot_Data"
    root.mkdir(parents=True, exist_ok=True)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _maybe_import_legacy_data(root: Path) -> None:
    target_db = root / "amp_bot.db"
    legacy_root = Path("data")
    legacy_db = legacy_root / "amp_bot.db"
    if target_db.exists() or not legacy_db.exists():
        return
    try:
        shutil.copy2(legacy_db, target_db)
        legacy_uploads = legacy_root / "uploads"
        target_uploads = root / "uploads"
        if legacy_uploads.exists():
            shutil.copytree(legacy_uploads, target_uploads, dirs_exist_ok=True)
    except OSError:
        pass


def _normalize_database_url(raw: str, root: Path) -> str:
    legacy_defaults = {
        "",
        "sqlite+aiosqlite:///./data/amp_bot.db",
        "sqlite+aiosqlite:///data/amp_bot.db",
    }
    if raw in legacy_defaults:
        return f"sqlite+aiosqlite:///{root / 'amp_bot.db'}"

    # Heroku provides postgres:// or postgresql://. SQLAlchemy asyncio must use
    # the asyncpg dialect explicitly.
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]

    # SQLAlchemy passes asyncpg URL query parameters to asyncpg.connect().
    # asyncpg expects the `ssl` argument (psycopg uses `sslmode`). Heroku
    # Postgres requires TLS, so production defaults to ssl=require.
    if raw.startswith("postgresql+asyncpg://") and os.getenv("DYNO") and "ssl=" not in raw and "sslmode=" not in raw:
        raw += ("&" if "?" in raw else "?") + "ssl=require"
    return raw


@dataclass(slots=True)
class Settings:
    bot_token: str = field(repr=False)
    database_url: str = field(repr=False)
    data_dir: str
    media_storage: str
    superadmin_ids: set[int]
    timezone: str
    organization_name: str
    bot_name: str
    public_base_url: str
    web_host: str
    web_port: int
    web_admin_username: str
    web_admin_password: str = field(repr=False)
    web_staff_accounts: dict[str, dict[str, str]] = field(repr=False)
    web_session_secret: str = field(repr=False)
    cookie_secure: bool
    season_name: str
    season_start: date
    season_end: date
    donation_jar_url: str = "https://send.monobank.ua/jar/5S531LWQuc"
    monobank_token: str = field(default="", repr=False)
    # v1.12.1 production stability: small explicit per-dyno PostgreSQL pools.
    # web + worker + temporary release dyno must stay below the provider limit.
    db_pool_size: int = 3
    db_max_overflow: int = 2
    db_pool_timeout: int = 10
    db_pool_recycle: int = 300
    worker_heartbeat_seconds: int = 30
    worker_stale_seconds: int = 120
    health_probe_timeout_seconds: int = 3
    health_startup_grace_seconds: int = 180
    scheduler_alert_repeat_seconds: int = 3600
    # Grace period before alerting about a never-confirmed external PostgreSQL backup.
    # GitHub/Heroku backup automation should normally verify a backup before this expires.
    backup_unknown_grace_hours: int = 24


def get_settings(require_bot_token: bool = True) -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if require_bot_token and not token:
        raise RuntimeError("Не задано BOT_TOKEN у .env")

    root = _data_dir()
    _maybe_import_legacy_data(root)

    raw_db = os.getenv("DATABASE_URL", "").strip()
    database_url = _normalize_database_url(raw_db, root)
    is_postgres = database_url.startswith("postgresql+asyncpg://")

    media_storage = os.getenv("MEDIA_STORAGE", "").strip().lower()
    if not media_storage:
        media_storage = "database" if is_postgres else "local"
    if media_storage not in {"local", "database"}:
        media_storage = "database" if is_postgres else "local"

    public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").strip().rstrip("/")

    web_session_secret = os.getenv("WEB_SESSION_SECRET", "").strip()
    if os.getenv("DYNO") and len(web_session_secret) < 32:
        raise RuntimeError("У production WEB_SESSION_SECRET має бути випадковим секретом щонайменше 32 символи.")
    if not web_session_secret:
        web_session_secret = "local-dev-session-secret"

    return Settings(
        bot_token=token,
        database_url=database_url,
        data_dir=str(root),
        media_storage=media_storage,
        superadmin_ids=_parse_ids(os.getenv("SUPERADMIN_IDS")),
        timezone=os.getenv("TIMEZONE", "Europe/Kyiv").strip(),
        organization_name=os.getenv("ORGANIZATION_NAME", "Анисівський молодіжний простір").strip(),
        bot_name=os.getenv("BOT_NAME", "АМПасадори / АМП XP").strip(),
        public_base_url=public_base_url,
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip(),
        web_port=int(os.getenv("PORT", os.getenv("WEB_PORT", "8080"))),
        web_admin_username=os.getenv("WEB_ADMIN_USERNAME", "admin").strip(),
        # Legacy/bootstrap-only credential. No insecure default is allowed.
        web_admin_password=os.getenv("WEB_ADMIN_PASSWORD", "").strip(),
        web_staff_accounts=_parse_staff_accounts(os.getenv("WEB_STAFF_ACCOUNTS_JSON")),
        web_session_secret=web_session_secret,
        cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), default=bool(os.getenv("DYNO"))),
        season_name=os.getenv("SEASON_NAME", "Сезон 2026/27").strip(),
        season_start=_parse_date(os.getenv("SEASON_START"), date(2026, 9, 1)),
        season_end=_parse_date(os.getenv("SEASON_END"), date(2027, 8, 31)),
        donation_jar_url=os.getenv("DONATION_JAR_URL", "https://send.monobank.ua/jar/5S531LWQuc").strip(),
        monobank_token=os.getenv("MONOBANK_TOKEN", "").strip(),
        db_pool_size=_env_int("DB_POOL_SIZE", 3, minimum=1, maximum=20),
        db_max_overflow=_env_int("DB_MAX_OVERFLOW", 2, minimum=0, maximum=20),
        db_pool_timeout=_env_int("DB_POOL_TIMEOUT", 10, minimum=1, maximum=120),
        db_pool_recycle=_env_int("DB_POOL_RECYCLE", 300, minimum=30, maximum=3600),
        worker_heartbeat_seconds=_env_int("WORKER_HEARTBEAT_SECONDS", 30, minimum=5, maximum=300),
        worker_stale_seconds=_env_int("WORKER_STALE_SECONDS", 120, minimum=30, maximum=3600),
        health_probe_timeout_seconds=_env_int("HEALTH_PROBE_TIMEOUT_SECONDS", 3, minimum=1, maximum=30),
        health_startup_grace_seconds=_env_int("HEALTH_STARTUP_GRACE_SECONDS", 180, minimum=30, maximum=1800),
        scheduler_alert_repeat_seconds=_env_int("SCHEDULER_ALERT_REPEAT_SECONDS", 3600, minimum=300, maximum=86400),
        backup_unknown_grace_hours=_env_int("BACKUP_UNKNOWN_GRACE_HOURS", 24, minimum=1, maximum=168),
    )
