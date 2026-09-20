from __future__ import annotations

import argparse
import asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.db import Database
from app.model_domains import User, UserRole


async def run(query: str, role: str) -> None:
    settings = get_settings(require_bot_token=False)
    db = Database(settings)
    await db.init()
    try:
        async with db.session_factory() as session:
            q = query.strip().lower()
            rows = list((await session.scalars(
                select(User).where(func.lower(User.full_name).like(f"%{q}%")).order_by(User.id)
            )).all())
            if not rows:
                raise SystemExit(f"Учасника за запитом «{query}» не знайдено.")
            if len(rows) > 1:
                print("Знайдено декілька профілів. Уточніть запит:")
                for u in rows:
                    print(f"  АМП-{u.id:04d} | {u.full_name} | @{u.username or '-'} | {u.role} | {u.status}")
                raise SystemExit(2)
            user = rows[0]
            old = user.role
            user.role = role
            await session.commit()
            print(f"✓ АМП-{user.id:04d} | {user.full_name}: роль {old} -> {role}")
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Змінити роль вже існуючого учасника без створення дубля.")
    parser.add_argument("--name", required=True, help="Частина ПІБ, наприклад: Вова Дорош")
    parser.add_argument("--role", default=UserRole.ADMIN.value, choices=[x.value for x in UserRole])
    args = parser.parse_args()
    asyncio.run(run(args.name, args.role))


if __name__ == "__main__":
    main()
