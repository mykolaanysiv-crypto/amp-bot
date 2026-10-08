from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from hashlib import sha256

from sqlalchemy import select

from app.config import get_settings
from app.db import Database
from app.media_storage import S3CompatibleMediaStorage
from app.model_domains import MediaAsset
from app.time_utils import clock


def _key(asset: MediaAsset, digest: str) -> str:
    safe_name = (asset.filename or f"media-{asset.id}").replace("/", "_")
    return f"amp-media/migrated/{asset.category}/{asset.id}-{digest[:16]}-{safe_name}"


async def run(mode: str, *, limit: int | None = None) -> int:
    settings = get_settings(require_bot_token=False)
    s3_settings = replace(settings, media_storage="s3")
    storage = S3CompatibleMediaStorage(s3_settings)
    db = Database(settings)
    await db.init()
    try:
        async with db.session_factory() as session:
            stmt = select(MediaAsset).order_by(MediaAsset.id.asc())
            if limit:
                stmt = stmt.limit(limit)
            assets = list((await session.scalars(stmt)).all())

        eligible = [a for a in assets if a.data is not None]
        print(f"mode={mode} assets={len(assets)} eligible_database_bytes={len(eligible)}")
        changed = 0

        for asset in eligible:
            payload = bytes(asset.data or b"")
            digest = sha256(payload).hexdigest()
            key = asset.migration_key or _key(asset, digest)

            if mode == "dry-run":
                print(f"DRY #{asset.id} {asset.category} {len(payload)} bytes -> {key}")
                continue

            if mode == "copy":
                storage.put_object(key, payload, asset.content_type or "application/octet-stream")
                async with db.session_factory() as session:
                    row = await session.get(MediaAsset, asset.id)
                    if row:
                        row.migration_key = key
                        row.checksum_sha256 = digest
                        row.last_verified_at = clock.storage_utc()
                        await session.commit()
                changed += 1
                print(f"COPY #{asset.id} -> {key}")
                continue

            if mode == "verify":
                remote = storage.get_object(key, asset.content_type or "application/octet-stream")
                ok = remote is not None and sha256(remote).hexdigest() == digest
                print(f"VERIFY #{asset.id} {'OK' if ok else 'FAIL'}")
                if not ok:
                    raise SystemExit(f"checksum verification failed for MediaAsset #{asset.id}")
                async with db.session_factory() as session:
                    row = await session.get(MediaAsset, asset.id)
                    if row:
                        row.migration_key = key
                        row.checksum_sha256 = digest
                        row.last_verified_at = clock.storage_utc()
                        row.integrity_status = "ok"
                        await session.commit()
                continue

            if mode == "switch":
                remote = storage.get_object(key, asset.content_type or "application/octet-stream")
                if remote is None or sha256(remote).hexdigest() != digest:
                    raise SystemExit(f"refusing switch: S3 checksum mismatch for MediaAsset #{asset.id}")
                async with db.session_factory() as session:
                    row = await session.get(MediaAsset, asset.id)
                    if row:
                        row.storage_backend = "s3"
                        row.storage_key = key
                        row.migration_key = key
                        row.checksum_sha256 = digest
                        row.integrity_status = "ok"
                        row.last_verified_at = clock.storage_utc()
                        # Intentionally keep row.data for safe rollback. No bytes are deleted here.
                        await session.commit()
                changed += 1
                print(f"SWITCH #{asset.id} -> s3 (database bytes retained)")
                continue

            if mode == "rollback":
                async with db.session_factory() as session:
                    row = await session.get(MediaAsset, asset.id)
                    if not row:
                        continue
                    if row.data is None:
                        raise SystemExit(f"refusing rollback: MediaAsset #{row.id} has no database bytes")
                    row.storage_backend = "database"
                    row.storage_key = None
                    row.integrity_status = "ok"
                    row.last_verified_at = clock.storage_utc()
                    await session.commit()
                changed += 1
                print(f"ROLLBACK #{asset.id} -> database")
                continue

            raise SystemExit(f"unknown mode: {mode}")

        print(f"done mode={mode} changed={changed}")
        return changed
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AMP v1.19.1 database -> S3-compatible media migration")
    parser.add_argument("mode", choices=["dry-run", "copy", "verify", "switch", "rollback"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.mode, limit=args.limit))


if __name__ == "__main__":
    main()
