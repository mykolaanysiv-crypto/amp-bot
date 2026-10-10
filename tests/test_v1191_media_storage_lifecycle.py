from __future__ import annotations

from pathlib import Path

import pytest

from app.media_integrity import scan_media_integrity
from app.media_storage import (
    MAX_MEDIA_BYTES,
    DatabaseMediaStorage,
    checksum_bytes,
    sniff_mime,
    validate_media_payload,
)
from app.model_domains import MediaAsset
from app.security import media_access_level

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v1191_release_contract():
    assert read("VERSION.txt").strip() == "1.20.3.1"
    assert read("VERSION_CHECK.txt").strip() == "1.20.3.1"
    migration = read("migrations/versions/20261008_0017_media_storage_lifecycle.py")
    assert 'revision: str = "20261008_0017"' in migration
    assert 'down_revision: Union[str, None] = "20261007_0016"' in migration
    for token in ("storage_backend", "checksum_sha256", "lifecycle_state", "quarantined_at", "last_verified_at"):
        assert token in migration


def test_storage_backends_and_migration_modes_are_present():
    source = read("app/media_storage.py")
    for token in ("class MediaStorage", "class DatabaseMediaStorage", "class LocalMediaStorage", "class S3CompatibleMediaStorage"):
        assert token in source
    migration = read("scripts/migrate_media_storage.py")
    for mode in ("dry-run", "copy", "verify", "switch", "rollback"):
        assert mode in migration
    assert "database bytes retained" in migration
    assert "checksum verification failed" in migration


def test_unknown_media_category_is_never_public():
    assert media_access_level("future-unknown-category") in {
        "participant_private", "staff_private", "superadmin_private"
    }
    assert media_access_level("future-unknown-category") != "public"


def test_mime_and_size_validation_uses_content_not_only_filename():
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 16
    assert sniff_mime(png, "fake.jpg") == "image/png"
    assert validate_media_payload(png, filename="image.png", claimed_mime="image/png", image_only=True) == "image/png"
    with pytest.raises(ValueError):
        validate_media_payload(png, filename="image.jpg", claimed_mime="image/jpeg", image_only=True)
    with pytest.raises(ValueError):
        validate_media_payload(b"x" * (MAX_MEDIA_BYTES + 1), filename="big.pdf")


@pytest.mark.asyncio
async def test_database_backend_contract_and_integrity_detection(db):
    storage = DatabaseMediaStorage()
    payload = b"%PDF-1.7\nAMP test\n"
    stored = await storage.store(db, payload, category="consents", filename="consent.pdf", content_type="application/pdf")
    assert stored.path.startswith("/media/")
    assert stored.checksum_sha256 == checksum_bytes(payload)

    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, stored.asset_id)
        assert asset is not None
        assert asset.storage_backend == "database"
        assert bytes(asset.data or b"") == payload

        # Same checksum = duplicate group.
        duplicate = MediaAsset(
            category="consents", filename="copy.pdf", content_type="application/pdf",
            detected_mime="application/pdf", data=payload, size_bytes=len(payload),
            checksum_sha256=stored.checksum_sha256, storage_backend="database",
            lifecycle_state="active", integrity_status="unknown",
        )
        session.add(duplicate)
        # Missing object: database backend without bytes.
        missing = MediaAsset(
            category="consents", filename="missing.pdf", content_type="application/pdf",
            data=None, size_bytes=12, checksum_sha256="0" * 64,
            storage_backend="database", lifecycle_state="active", integrity_status="unknown",
        )
        session.add(missing)
        # Corrupt: actual bytes do not match declared checksum.
        corrupt = MediaAsset(
            category="consents", filename="corrupt.pdf", content_type="application/pdf",
            data=b"%PDF-corrupt", size_bytes=12, checksum_sha256="f" * 64,
            storage_backend="database", lifecycle_state="active", integrity_status="unknown",
        )
        session.add(corrupt)
        oversized = MediaAsset(
            category="consents", filename="oversized.pdf", content_type="application/pdf",
            data=b"%PDF-small", size_bytes=MAX_MEDIA_BYTES + 1,
            checksum_sha256=checksum_bytes(b"%PDF-small"), storage_backend="database",
            lifecycle_state="active", integrity_status="unknown",
        )
        session.add(oversized)
        await session.commit()

    report = await scan_media_integrity(db, deep=True)
    assert report["duplicate_groups"]
    assert report["missing_ids"]
    assert report["corrupt_ids"]
    assert report["oversized_ids"]
    assert report["orphan_ids"]


def test_media_center_is_superadmin_and_hard_delete_is_guarded():
    route = read("app/web/routes/media_integrity.py")
    assert "guard_superadmin" in route
    assert "lifecycle_state != 'quarantine'" in route
    assert "media_reference_count" in route
    assert "confirmation.strip().upper() != 'ВИДАЛИТИ'" in route
    template = read("app/web/templates/media_integrity.html")
    for token in ("Без активних посилань", "Відсутні файли", "Групи дублікатів", "Некоректний MIME", "Завеликі файли", "Життєвий цикл"):
        assert token in template
