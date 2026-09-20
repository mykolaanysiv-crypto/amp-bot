from __future__ import annotations

from app.time_utils import clock

import argparse
import asyncio
import mimetypes
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, LargeBinary, String, Text, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.model_domains import Base, MediaAsset

IMAGE_TABLES = ("events", "quests", "volunteer_tasks", "rewards", "request_cases")


def normalize_target_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]
    if raw.startswith("postgresql+asyncpg://") and "ssl=" not in raw and "sslmode=" not in raw:
        raw += ("&" if "?" in raw else "?") + "ssl=require"
    return raw


def convert_value(value, column):
    if value is None:
        return None
    t = column.type
    if isinstance(t, DateTime):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    if isinstance(t, Date):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value)[:10])
    if isinstance(t, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(t, (Integer, BigInteger)):
        return int(value)
    if isinstance(t, Float):
        return float(value)
    if isinstance(t, LargeBinary):
        return bytes(value)
    if isinstance(t, (String, Text)):
        return str(value)
    return value


def source_schema(conn: sqlite3.Connection) -> tuple[set[str], dict[str, set[str]]]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns: dict[str, set[str]] = {}
    for table in tables:
        columns[table] = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    return tables, columns


async def migrate(args) -> None:
    sqlite_path = Path(args.sqlite).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite база не знайдена: {sqlite_path}")

    raw_target = os.getenv("TARGET_DATABASE_URL", "").strip()
    if not raw_target:
        raise SystemExit("Не задано TARGET_DATABASE_URL. Отримайте його через heroku config:get DATABASE_URL ...")
    target_url = normalize_target_url(raw_target)
    if not target_url.startswith("postgresql+asyncpg://"):
        raise SystemExit("TARGET_DATABASE_URL має вказувати на PostgreSQL.")

    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    src_tables, src_columns = source_schema(src)

    # v1.17.1: target schema is provisioned exclusively through Alembic.
    from scripts.alembic_bootstrap import upgrade_head
    await asyncio.to_thread(upgrade_head, target_url)

    engine = create_async_engine(target_url, pool_pre_ping=True)
    try:
        async with engine.begin() as target:

            existing_users = 0
            if "users" in Base.metadata.tables:
                existing_users = int((await target.execute(select(func.count()).select_from(Base.metadata.tables["users"]))).scalar_one())
            if existing_users and not args.force:
                raise SystemExit(
                    f"Цільова PostgreSQL база вже містить {existing_users} користувачів. "
                    "Міграцію зупинено. Використовуйте --force лише для свідомого повного перезапису нової бази."
                )

            if args.force:
                for table in reversed(Base.metadata.sorted_tables):
                    await target.execute(table.delete())

            deferred_user_referrals: list[tuple[int, int]] = []
            copied = 0
            for table in Base.metadata.sorted_tables:
                name = table.name
                if name == "media_assets" or name not in src_tables:
                    continue
                common = [c.name for c in table.columns if c.name in src_columns.get(name, set())]
                if not common:
                    continue
                query = f'SELECT {", ".join([chr(34)+c+chr(34) for c in common])} FROM "{name}"'
                rows = src.execute(query).fetchall()
                if not rows:
                    continue
                payload = []
                for row in rows:
                    item = {}
                    for col_name in common:
                        value = row[col_name]
                        if name == "users" and col_name == "referred_by_user_id" and value is not None:
                            deferred_user_referrals.append((int(row["id"]), int(value)))
                            value = None
                        item[col_name] = convert_value(value, table.c[col_name])
                    payload.append(item)
                await target.execute(table.insert(), payload)
                copied += len(payload)
                print(f"✓ {name}: {len(payload)}")

            if deferred_user_referrals:
                users = Base.metadata.tables["users"]
                for user_id, referrer_id in deferred_user_referrals:
                    await target.execute(users.update().where(users.c.id == user_id).values(referred_by_user_id=referrer_id))

            # Move legacy local uploads into PostgreSQL-backed media so they survive Heroku restarts.
            media_count = 0
            missing_files = 0
            for table_name in IMAGE_TABLES:
                if table_name not in Base.metadata.tables:
                    continue
                table = Base.metadata.tables[table_name]
                if "image_path" not in table.c:
                    continue
                result = await target.execute(select(table.c.id, table.c.image_path).where(table.c.image_path.like("/uploads/%")))
                for row_id, image_path in result.all():
                    fp = data_dir / str(image_path).lstrip("/")
                    if not fp.exists():
                        print(f"! Не знайдено фото: {fp}")
                        missing_files += 1
                        continue
                    raw = fp.read_bytes()
                    content_type = mimetypes.guess_type(fp.name)[0] or "image/webp"
                    asset_result = await target.execute(
                        MediaAsset.__table__.insert().values(
                            category=table_name,
                            filename=fp.name,
                            content_type=content_type,
                            data=raw,
                            size_bytes=len(raw),
                            created_at=clock.storage_utc(),
                        ).returning(MediaAsset.id)
                    )
                    asset_id = int(asset_result.scalar_one())
                    await target.execute(table.update().where(table.c.id == row_id).values(image_path=f"/media/{asset_id}"))
                    media_count += 1

            # Reset PostgreSQL serial sequences after explicit ID inserts.
            for table in Base.metadata.sorted_tables:
                if "id" not in table.c:
                    continue
                name = table.name.replace("'", "''")
                await target.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{name}\"), 1), "
                    f"COALESCE((SELECT MAX(id) IS NOT NULL FROM \"{name}\"), false))"
                ))

            print(f"\nГотово: перенесено {copied} записів і {media_count} фото.")
            if missing_files:
                print(f"Увага: {missing_files} локальних фото не знайдено; перевірте --data-dir.")
    finally:
        src.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Перенесення AMP XP з локальної SQLite у Heroku Postgres")
    parser.add_argument("--sqlite", default=str(Path.home() / "AMP_Bot_Data" / "amp_bot.db"))
    parser.add_argument("--data-dir", default=str(Path.home() / "AMP_Bot_Data"))
    parser.add_argument("--force", action="store_true", help="Очистити цільові таблиці перед імпортом. Використовуйте лише для нової/тестової БД.")
    args = parser.parse_args()
    asyncio.run(migrate(args))


if __name__ == "__main__":
    main()
