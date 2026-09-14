from __future__ import annotations

import argparse
import secrets
import subprocess
import json
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

    app_url = f"https://{args.app}.herokuapp.com"
    try:
        info = subprocess.run(
            ["heroku", "apps:info", "-a", args.app, "--json"],
            check=True, capture_output=True, text=True,
        )
        parsed = json.loads(info.stdout or "{}")
        app_url = str(parsed.get("web_url") or app_url).rstrip("/")
    except Exception:
        pass

    config = {
        "BOT_TOKEN": values["BOT_TOKEN"].strip(),
        "SUPERADMIN_IDS": values["SUPERADMIN_IDS"].strip(),
        "WEB_ADMIN_USERNAME": values.get("WEB_ADMIN_USERNAME", "admin").strip() or "admin",
        "WEB_SESSION_SECRET": session_secret,
        "TIMEZONE": values.get("TIMEZONE", "Europe/Kyiv").strip() or "Europe/Kyiv",
        "BOT_NAME": values.get("BOT_NAME", "АМПасадори / АМП XP").strip() or "АМПасадори / АМП XP",
        "ORGANIZATION_NAME": values.get("ORGANIZATION_NAME", "Анисівський молодіжний простір").strip() or "Анисівський молодіжний простір",
        "PUBLIC_BASE_URL": app_url,
        "MEDIA_STORAGE": "database",
        "COOKIE_SECURE": "1",
        "SEASON_NAME": values.get("SEASON_NAME", "Сезон 2026/27").strip() or "Сезон 2026/27",
        "SEASON_START": values.get("SEASON_START", "2026-09-01").strip() or "2026-09-01",
        "SEASON_END": values.get("SEASON_END", "2027-08-31").strip() or "2027-08-31",
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
