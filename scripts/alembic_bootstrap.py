from __future__ import annotations

from alembic import command
from alembic.config import Config

from app.config import get_settings


def _cfg(database_url: str | None = None) -> Config:
    cfg = Config("alembic.ini")
    url = (database_url or get_settings(require_bot_token=False).database_url).strip()
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(revision: str, database_url: str | None = None) -> None:
    command.upgrade(_cfg(database_url), revision)


def upgrade_head(database_url: str | None = None) -> None:
    """Apply the canonical Alembic chain to head.

    v1.17.1 removes the legacy schema bootstrap. This is the only supported
    schema-mutation path for production and CI.
    """
    upgrade("head", database_url)


def downgrade(revision: str, database_url: str | None = None) -> None:
    command.downgrade(_cfg(database_url), revision)


def current(database_url: str | None = None) -> None:
    command.current(_cfg(database_url))


if __name__ == "__main__":
    upgrade_head()
