from __future__ import annotations

"""Fail when SQLAlchemy models and the Alembic-managed database diverge.

This is the v1.17.1 guard that prevents a new mapped table/column/index from
reaching production without an Alembic revision. It compares the database at
``alembic head`` with canonical ``app.model_domains.Base.metadata``.
"""

import asyncio
import json
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.model_domains import Base


# Production may still carry duplicate pre-v1.17.1 indexes created by the old
# runtime bootstrap. They are harmless and not part of the canonical model.
LEGACY_EXTRA_INDEXES = {
    "ux_users_public_token",
    "ux_users_referral_code",
    "ux_events_share_token",
}


def _filtered_diffs(sync_connection) -> list[Any]:
    context = MigrationContext.configure(
        sync_connection,
        opts={
            "compare_type": True,
            "compare_server_default": False,
            "target_metadata": Base.metadata,
        },
    )
    raw = list(compare_metadata(context, Base.metadata))
    filtered: list[Any] = []
    for diff in raw:
        # Alembic shape: ('remove_index', Index(...))
        if isinstance(diff, tuple) and diff and diff[0] == "remove_index":
            idx = diff[1] if len(diff) > 1 else None
            if getattr(idx, "name", None) in LEGACY_EXTRA_INDEXES:
                continue
        filtered.append(diff)
    return filtered


async def collect_schema_diffs(database_url: str | None = None) -> list[Any]:
    url = (database_url or get_settings(require_bot_token=False).database_url).strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_filtered_diffs)
    finally:
        await engine.dispose()


def _safe_repr(diff: Any) -> str:
    try:
        return repr(diff)
    except Exception:
        return f"<{type(diff).__name__}>"


def main() -> None:
    diffs = asyncio.run(collect_schema_diffs())
    if diffs:
        payload = [_safe_repr(item) for item in diffs]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(
            "Schema drift detected: SQLAlchemy metadata differs from Alembic head. "
            "Create an Alembic revision; do not modify schema from application startup."
        )
    print("Schema drift check PASS: Alembic head matches canonical models")


if __name__ == "__main__":
    main()
