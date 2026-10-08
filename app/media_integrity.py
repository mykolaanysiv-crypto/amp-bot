from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import func, select

from .config import get_settings
from .db import Database
from .media_storage import MAX_MEDIA_BYTES, checksum_bytes, read_media_asset_bytes, sniff_mime
from .model_domains import Base, MediaAsset
from .time_utils import clock


def _canonical_media_id(path: object) -> int | None:
    if not isinstance(path, str) or not path.startswith('/media/'):
        return None
    tail = path.rstrip('/').split('/')[-1]
    return int(tail) if tail.isdigit() else None


async def referenced_media_ids(session) -> set[int]:
    ids: set[int] = set()
    for table in Base.metadata.sorted_tables:
        if table.name == MediaAsset.__tablename__:
            continue
        for column in table.columns:
            if not column.name.endswith('_path'):
                continue
            rows = (await session.execute(select(column).where(column.like('/media/%')))).scalars().all()
            for value in rows:
                asset_id = _canonical_media_id(value)
                if asset_id is not None:
                    ids.add(asset_id)
    return ids


async def media_reference_count(session, asset_id: int) -> int:
    total = 0
    target = f'/media/{asset_id}'
    for table in Base.metadata.sorted_tables:
        if table.name == MediaAsset.__tablename__:
            continue
        for column in table.columns:
            if column.name.endswith('_path'):
                total += int(await session.scalar(select(func.count()).select_from(table).where(column == target)) or 0)
    return total


async def scan_media_integrity(db: Database, *, deep: bool = False, remote_limit: int = 250) -> dict:
    settings = get_settings(require_bot_token=False)
    async with db.session_factory() as session:
        assets = list((await session.scalars(select(MediaAsset).order_by(MediaAsset.id.asc()))).all())
        refs = await referenced_media_ids(session)

    backend_counts = Counter((a.storage_backend or 'database') for a in assets)
    lifecycle_counts = Counter((a.lifecycle_state or 'active') for a in assets)
    db_bytes = sum(len(a.data or b'') for a in assets)
    total_bytes = sum(int(a.size_bytes or 0) for a in assets)
    orphan_ids = [a.id for a in assets if a.id not in refs]
    oversized = [a.id for a in assets if int(a.size_bytes or 0) > MAX_MEDIA_BYTES]
    invalid_mime: list[int] = []
    missing: list[int] = []
    corrupt: list[int] = []
    verified = 0
    remote_checked = 0

    checksum_groups: dict[str, list[int]] = defaultdict(list)
    for a in assets:
        if a.checksum_sha256:
            checksum_groups[a.checksum_sha256].append(a.id)
        if a.detected_mime and a.content_type and a.detected_mime != a.content_type:
            invalid_mime.append(a.id)

    if deep:
        for a in assets:
            if (a.storage_backend or 'database') == 's3':
                if remote_checked >= remote_limit:
                    continue
                remote_checked += 1
            async with db.session_factory() as session:
                fresh = await session.get(MediaAsset, a.id)
                if not fresh:
                    continue
                payload = await read_media_asset_bytes(db, fresh)
                if payload is None:
                    fresh.integrity_status = 'missing'
                    missing.append(fresh.id)
                else:
                    actual_checksum = checksum_bytes(payload)
                    detected = sniff_mime(payload, fresh.filename)
                    if fresh.checksum_sha256 and fresh.checksum_sha256 != actual_checksum:
                        fresh.integrity_status = 'corrupt'
                        corrupt.append(fresh.id)
                    else:
                        fresh.checksum_sha256 = actual_checksum
                        fresh.detected_mime = detected
                        fresh.size_bytes = len(payload)
                        fresh.integrity_status = 'ok'
                        fresh.last_verified_at = clock.storage_utc()
                        verified += 1
                    if fresh.content_type and detected != fresh.content_type:
                        invalid_mime.append(fresh.id)
                await session.commit()

    duplicates = {digest: ids for digest, ids in checksum_groups.items() if len(ids) > 1}

    local_orphans: list[str] = []
    root = Path(settings.data_dir)
    # Legacy/local paths are still supported. We surface untracked files, but never delete them automatically.
    for root_name in ('uploads', 'private'):
        base = root / root_name
        if base.exists():
            for fp in base.rglob('*'):
                if fp.is_file():
                    local_orphans.append(str(fp.relative_to(root)))
                    if len(local_orphans) >= 50:
                        break

    quarantine_candidates = [a.id for a in assets if (a.lifecycle_state or 'active') in {'candidate', 'reviewed', 'quarantine'}]
    return {
        'total_media': len(assets),
        'total_bytes': total_bytes,
        'db_storage_bytes': db_bytes,
        'backend_counts': dict(backend_counts),
        'lifecycle_counts': dict(lifecycle_counts),
        'orphan_ids': orphan_ids,
        'local_files_sample': local_orphans,
        'missing_ids': sorted(set(missing)),
        'duplicate_groups': duplicates,
        'invalid_mime_ids': sorted(set(invalid_mime)),
        'oversized_ids': oversized,
        'corrupt_ids': sorted(set(corrupt)),
        'quarantine_candidates': quarantine_candidates,
        'verified': verified,
        'remote_checked': remote_checked,
        'remote_scan_truncated': deep and backend_counts.get('s3', 0) > remote_checked,
        'deep': deep,
    }
