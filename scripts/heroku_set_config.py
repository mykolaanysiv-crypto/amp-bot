from __future__ import annotations

import argparse
import secrets
import subprocess
import json
import sys
from pathlib import Path

from dotenv import dotenv_values


APP_DEFAULT = "amp-bot-ver-1-5-0"


def main() -> None:
    parser = argparse.ArgumentParser(description="Передати AMP XP config vars з локального .env у Heroku")
    parser.add_argument("--app", default=APP_DEFAULT)
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    env_path = Path(args.env_file).expanduser().resolve()
    if not env_path.exists():
        raise SystemExit(f"Не знайдено {env_path}. Скопіюйте .env з попередньої версії.")

    values = {k: (v or "") for k, v in dotenv_values(env_path).items() if k}
    required = ["BOT_TOKEN", "SUPERADMIN_IDS"]
    missing = [k for k in required if not values.get(k, "").strip()]
    if missing:
        raise SystemExit("У .env відсутні обов'язкові значення: " + ", ".join(missing))

    session_secret = values.get("WEB_SESSION_SECRET", "").strip()
    if not session_secret or session_secret in {"change-this-secret", "CHANGE_ME_LONG_RANDOM_SECRET"}:
        session_secret = secrets.token_urlsafe(48)
        print("WEB_SESSION_SECRET був відсутній/тестовий — для Heroku згенеровано новий безпечний секрет.")

    # v1.18.6: field encryption gets its own root key. When migrating from older
    # releases, keep the session secret in the previous-key ring so existing
    # ciphertext remains readable until rotate_field_encryption is run.
    field_key = values.get("FIELD_ENCRYPTION_KEY", "").strip()
    previous_field_keys = [part.strip() for part in values.get("FIELD_ENCRYPTION_PREVIOUS_KEYS", "").split(",") if part.strip()]
    if len(field_key) < 32 or field_key == session_secret:
        field_key = secrets.token_urlsafe(48)
        if session_secret not in previous_field_keys:
            previous_field_keys.append(session_secret)
        print("FIELD_ENCRYPTION_KEY був відсутній/небезпечний — згенеровано окремий ключ; WEB_SESSION_SECRET додано як legacy previous key.")

    app_url = f"https://{args.app}.herokuapp.com"
    try:
        info = subprocess.run(
            ["heroku", "apps:info", "-a", args.app, "--json"],
            check=True, capture_output=True, text=True,
        )
        parsed = json.loads(info.stdout or "{}")
        app_url = str(parsed.get("web_url") or app_url).rstrip("/")
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        print(f"WARN HEROKU_APP_INFO_LOOKUP_FAILED: {type(exc).__name__}; використовую fallback URL", file=sys.stderr)

    config = {
        "BOT_TOKEN": values["BOT_TOKEN"].strip(),
        "SUPERADMIN_IDS": values["SUPERADMIN_IDS"].strip(),
        "WEB_ADMIN_USERNAME": values.get("WEB_ADMIN_USERNAME", "admin").strip() or "admin",
        "WEB_SESSION_SECRET": session_secret,
        "FIELD_ENCRYPTION_KEY": field_key,
        "FIELD_ENCRYPTION_PREVIOUS_KEYS": ",".join(previous_field_keys),
        "TIMEZONE": values.get("TIMEZONE", "Europe/Kyiv").strip() or "Europe/Kyiv",
        "BOT_NAME": values.get("BOT_NAME", "АМПасадори / АМП XP").strip() or "АМПасадори / АМП XP",
        "ORGANIZATION_NAME": values.get("ORGANIZATION_NAME", "Анисівський молодіжний простір").strip() or "Анисівський молодіжний простір",
        "PUBLIC_BASE_URL": app_url,
        "MEDIA_STORAGE": "database",
        "COOKIE_SECURE": "1",
        "SEASON_NAME": values.get("SEASON_NAME", "Сезон 2026/27").strip() or "Сезон 2026/27",
        "SEASON_START": values.get("SEASON_START", "2026-09-01").strip() or "2026-09-01",
        "SEASON_END": values.get("SEASON_END", "2027-08-31").strip() or "2027-08-31",
        "BACKUP_UNKNOWN_GRACE_HOURS": values.get("BACKUP_UNKNOWN_GRACE_HOURS", "24").strip() or "24",
        "BACKUP_WARNING_AGE_HOURS": values.get("BACKUP_WARNING_AGE_HOURS", "36").strip() or "36",
        "BACKUP_MAX_AGE_HOURS": values.get("BACKUP_MAX_AGE_HOURS", "48").strip() or "48",
        "WEB_MAX_REQUEST_MB": values.get("WEB_MAX_REQUEST_MB", "25").strip() or "25",
    }

    # v1.7.3 stores web credentials hashed in PostgreSQL. These legacy values
    # are sent only when explicitly present so they can bootstrap/migrate an
    # existing installation once. Remove them after login verification.
    legacy_password = values.get("WEB_ADMIN_PASSWORD", "").strip()
    if legacy_password:
        config["WEB_ADMIN_PASSWORD"] = legacy_password
        print("УВАГА: WEB_ADMIN_PASSWORD передається лише як legacy bootstrap. Після міграції видаліть його з Heroku Config Vars.")

    staff_json = values.get("WEB_STAFF_ACCOUNTS_JSON", "").strip()
    if staff_json:
        try:
            parsed_staff = json.loads(staff_json)
            if isinstance(parsed_staff, dict):
                config["WEB_STAFF_ACCOUNTS_JSON"] = json.dumps(parsed_staff, ensure_ascii=False, separators=(",", ":"))
        except json.JSONDecodeError:
            raise SystemExit("WEB_STAFF_ACCOUNTS_JSON має некоректний JSON у .env")

    cmd = ["heroku", "config:set", *[f"{k}={v}" for k, v in config.items()], "-a", args.app]
    subprocess.run(cmd, check=True)
    print(f"✓ Config vars передано в Heroku app {args.app}.")
    print("DATABASE_URL не змінювався: ним керує Heroku Postgres.")


if __name__ == "__main__":
    main()
