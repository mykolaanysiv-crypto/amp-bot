from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.db import Database
from app.models import WebStaffAccount
from app.security import generate_temporary_password, hash_password, password_errors

APP_DEFAULT = "amp-bot-ver-1-5-0"


async def _upsert(args) -> None:
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    await db.init()
    password = args.password.strip() or generate_temporary_password()
    errors = password_errors(password, username=args.username)
    if errors:
        raise SystemExit("Пароль не відповідає вимогам: " + ", ".join(errors))
    async with db.session_factory() as session:
        row = await session.scalar(select(WebStaffAccount).where(WebStaffAccount.username == args.username.strip()))
        if not row:
            row = WebStaffAccount(
                username=args.username.strip(),
                display_name=args.display_name.strip(),
                password_hash=hash_password(password),
                role="admin",
                active=True,
                must_change_password=True,
                two_factor_enabled=bool(args.two_factor_tg_id),
                two_factor_tg_id=args.two_factor_tg_id or None,
                created_at=datetime.utcnow(),
                password_changed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
        else:
            row.display_name = args.display_name.strip()
            row.password_hash = hash_password(password)
            row.active = True
            row.must_change_password = True
            row.failed_attempts = 0
            row.locked_until = None
            row.two_factor_enabled = bool(args.two_factor_tg_id) or row.two_factor_enabled
            if args.two_factor_tg_id:
                row.two_factor_tg_id = args.two_factor_tg_id
            row.password_changed_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
        await session.commit()
    await db.close()
    print(f"✓ Web-admin {args.display_name} ({args.username}) створено/оновлено в БД.")
    print(f"Тимчасовий пароль: {password}")
    print("Після першого входу користувач буде зобов'язаний змінити пароль.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Створити/оновити іменний web-admin з хешованим паролем у БД.")
    parser.add_argument("--app", default="", help="Heroku app. Якщо задано — скрипт запуститься через heroku run.")
    parser.add_argument("--direct", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--password", default="")
    parser.add_argument("--two-factor-tg-id", type=int, default=0)
    args = parser.parse_args()

    if args.app and not args.direct:
        command = [
            "heroku", "run", "--exit-code", "-a", args.app, "--",
            "python", "scripts/add_staff_account.py", "--direct",
            "--username", args.username,
            "--display-name", args.display_name,
        ]
        if args.password:
            command += ["--password", args.password]
        if args.two_factor_tg_id:
            command += ["--two-factor-tg-id", str(args.two_factor_tg_id)]
        raise SystemExit(subprocess.call(command))

    asyncio.run(_upsert(args))


if __name__ == "__main__":
    main()
