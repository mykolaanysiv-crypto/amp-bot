from __future__ import annotations

from .time_utils import clock

import asyncio
import logging
import shutil
import time
from pathlib import Path
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings
from .metrics import runtime_metrics

log = logging.getLogger(__name__)

# Web and worker processes may initialize database access independently.
# Serialize SQLite initialization inside a process.
_db_init_lock = asyncio.Lock()


class Database:
    def __init__(self, settings: Settings):
        _backup_sqlite_before_start(settings)
        self.settings = settings
        engine_kwargs = {
            "echo": False,
            "future": True,
            "pool_pre_ping": True,
        }
        if settings.database_url.startswith("postgresql+asyncpg://"):
            # v1.12.1: bound every dyno to a predictable PostgreSQL connection budget.
            # web, worker and release dynos each own a separate SQLAlchemy pool.
            engine_kwargs.update(
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_recycle=settings.db_pool_recycle,
            )
        self.engine: AsyncEngine = create_async_engine(settings.database_url, **engine_kwargs)
        self._install_query_metrics()
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    def _install_query_metrics(self) -> None:
        """Measure DB execution latency without recording SQL text or bind values."""
        sync_engine = self.engine.sync_engine

        @event.listens_for(sync_engine, "before_cursor_execute")
        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
            stack = conn.info.setdefault("amp_query_started", [])
            stack.append(time.perf_counter())

        def _finish_query(conn) -> None:
            stack = conn.info.get("amp_query_started") or []
            if not stack:
                return
            started = stack.pop()
            runtime_metrics.record_db(duration_ms=(time.perf_counter() - started) * 1000.0)

        @event.listens_for(sync_engine, "after_cursor_execute")
        def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
            _finish_query(conn)

        @event.listens_for(sync_engine, "handle_error")
        def _handle_error(exception_context):
            # SQLAlchemy may report an engine-level failure before a Connection
            # object exists. Observability must never mask the original DB error.
            conn = exception_context.connection
            if conn is not None:
                _finish_query(conn)

    async def init(self) -> None:
        """Initialize the runtime connection only.

        v1.17.1 removes all schema mutation from application startup. Production
        schema changes are applied exclusively by Alembic in the release phase.
        SQLite PRAGMAs remain runtime connection settings, not migrations.
        """
        async with _db_init_lock:
            async with self.engine.begin() as conn:
                if self.engine.url.get_backend_name() == "sqlite":
                    try:
                        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                        await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                    except Exception as exc:
                        log.debug("SQLite PRAGMA setup skipped: %s", exc)
                # Force a real connection/transaction so startup fails fast if the
                # database is unavailable, but never create/alter schema here.
                await conn.exec_driver_sql("SELECT 1")

    async def close(self) -> None:
        await self.engine.dispose()

    def pool_status(self) -> dict[str, int | str | None]:
        """Return non-sensitive SQLAlchemy pool telemetry for health endpoints."""
        pool = self.engine.pool
        data: dict[str, int | str | float | None] = {
            "backend": self.engine.url.get_backend_name(),
            "size": None,
            "checked_in": None,
            "checked_out": None,
            "overflow": None,
            "configured_pool_size": self.settings.db_pool_size if self.engine.url.get_backend_name() == "postgresql" else None,
            "configured_max_overflow": self.settings.db_max_overflow if self.engine.url.get_backend_name() == "postgresql" else None,
            "max_capacity": (self.settings.db_pool_size + self.settings.db_max_overflow) if self.engine.url.get_backend_name() == "postgresql" else None,
            "utilization_pct": None,
        }
        for key, method_name in (
            ("size", "size"),
            ("checked_in", "checkedin"),
            ("checked_out", "checkedout"),
            ("overflow", "overflow"),
        ):
            method = getattr(pool, method_name, None)
            if callable(method):
                try:
                    data[key] = int(method())
                except Exception:
                    data[key] = None
        max_capacity = data.get("max_capacity")
        checked_out = data.get("checked_out")
        if isinstance(max_capacity, int) and max_capacity > 0 and isinstance(checked_out, int):
            data["utilization_pct"] = round(checked_out * 100 / max_capacity, 1)
        return data


def _backup_sqlite_before_start(settings: Settings) -> None:
    """Create a lightweight daily safety copy before application startup.

    Operational data live outside the version folder, so this backup is also
    preserved when a new application archive is unpacked.
    """
    if not settings.database_url.startswith("sqlite+aiosqlite:///"):
        return
    raw = settings.database_url.removeprefix("sqlite+aiosqlite:///")
    db_path = Path(raw).expanduser()
    if not db_path.exists() or db_path.stat().st_size == 0:
        return
    backup_dir = Path(settings.data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = clock.now_local().strftime("%Y-%m-%d")
    target = backup_dir / f"amp_bot_{stamp}.db"
    if target.exists():
        return
    try:
        shutil.copy2(db_path, target)
    except OSError as exc:
        log.warning("Не вдалося створити резервну копію SQLite: %s", exc)
