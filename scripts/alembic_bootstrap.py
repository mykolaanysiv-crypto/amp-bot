from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import get_settings


def _cfg() -> Config:
    cfg = Config("alembic.ini")
    settings = get_settings(require_bot_token=False)
    cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return cfg


def stamp_baseline_if_needed() -> str:
    """Adopt Alembic after the legacy compatibility bootstrap.

    v1.12.0 has no new schema delta, so existing databases can be safely stamped
    at the baseline. Future releases run normal ``upgrade head`` migrations.
    """
    from sqlalchemy import create_engine
    settings = get_settings(require_bot_token=False)
    url = settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        # Alembic itself handles asyncpg; inspection here uses Alembic command
        # path instead of opening a second synchronous driver.
        try:
            command.current(_cfg())
        except Exception:
            command.stamp(_cfg(), "head")
            return "stamped"
        # command.current succeeds even when no version rows exist, so upgrade
        # is harmless for our no-op baseline and creates the version table.
        command.upgrade(_cfg(), "head")
        return "upgraded"
    # SQLite path: direct inspection is available through sqlite3-compatible URL
    command.upgrade(_cfg(), "head")
    return "upgraded"


def upgrade_head() -> None:
    command.upgrade(_cfg(), "head")


if __name__ == "__main__":
    upgrade_head()
