from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile
from PIL import Image, ImageOps
from sqlalchemy import select

from .config import get_settings
from .db import Database
from .media_storage import (
    MAX_MEDIA_BYTES,
    checksum_bytes,
    get_media_storage,
    read_media_asset_bytes,
    sniff_mime,
    validate_media_payload,
)
from .model_domains import MediaAsset
from .time_utils import clock


def normalize_image_bytes(raw: bytes) -> bytes:
    """Normalize an uploaded image to compact WebP without cropping."""
    try:
        img = Image.open(BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, "white")
            background.paste(img, mask=img.getchannel("A"))
            img = background
        img = img.convert("RGB")
        max_size = (1080, 1350) if img.height >= img.width else (1200, 1200)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, "WEBP", quality=88, method=6)
        return output.getvalue()
    except Exception as exc:
        raise ValueError("Не вдалося обробити фото. Надішліть JPG, PNG або WebP.") from exc


def normalize_transparent_png_bytes(raw: bytes) -> bytes:
    """Normalize ambassador badge artwork while preserving alpha transparency."""
    try:
        img = Image.open(BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGBA")
        img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, "PNG", optimize=True)
        return output.getvalue()
    except Exception as exc:
        raise ValueError("Не вдалося обробити PNG. Завантажте коректне PNG-зображення.") from exc


async def store_image_bytes(db: Database, raw: bytes, category: str, *, original_name: str = "image") -> str:
    """Validate, normalize and store an image through the configured MediaStorage backend."""
    validate_media_payload(raw, filename=original_name, image_only=True, max_bytes=MAX_MEDIA_BYTES)
    normalized = normalize_image_bytes(raw)
    filename = f"{uuid4().hex}.webp"
    stored = await get_media_storage().store(
        db, normalized, category=category, filename=filename, content_type="image/webp"
    )
    return stored.path


async def store_transparent_png(db: Database, raw: bytes, category: str, *, original_name: str = "badge.png") -> str:
    validate_media_payload(raw, filename=original_name, image_only=True, max_bytes=MAX_MEDIA_BYTES)
    normalized = normalize_transparent_png_bytes(raw)
    filename = f"{uuid4().hex}.png"
    stored = await get_media_storage().store(
        db, normalized, category=category, filename=filename, content_type="image/png"
    )
    return stored.path


async def store_file_bytes(
    db: Database,
    raw: bytes,
    category: str,
    *,
    original_name: str = "file",
    content_type: str = "application/octet-stream",
) -> str:
    """Validate and store a supported arbitrary document through MediaStorage."""
    detected = validate_media_payload(
        raw,
        filename=original_name,
        claimed_mime=content_type,
        image_only=False,
        max_bytes=MAX_MEDIA_BYTES,
    )
    suffix = Path(original_name or "file").suffix.lower()[:10]
    filename = f"{uuid4().hex}{suffix}"
    stored = await get_media_storage().store(
        db, raw, category=category, filename=filename, content_type=detected
    )
    return stored.path


async def delete_stored_image(db: Database, image_path: str | None) -> None:
    """Detach-safe delete: database media are quarantined, never hard-deleted automatically."""
    if not image_path:
        return
    if image_path.startswith("/media/"):
        try:
            asset_id = int(image_path.rstrip("/").split("/")[-1])
        except ValueError:
            return
        async with db.session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            if asset:
                asset.lifecycle_state = "quarantine"
                asset.quarantined_at = clock.storage_utc()
                asset.integrity_status = "pending_review"
                await session.commit()
        return

    # Legacy/local paths are moved into quarantine instead of being silently destroyed.
    if image_path.startswith(("/uploads/", "/private/")):
        settings = get_settings(require_bot_token=False)
        root = Path(settings.data_dir).resolve()
        fp = (root / image_path.lstrip("/")).resolve()
        if root not in fp.parents or not fp.exists() or not fp.is_file():
            return
        quarantine = root / "quarantine" / image_path.lstrip("/")
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        try:
            fp.replace(quarantine)
        except OSError:
            pass


def media_file(image_path: str | None) -> Path | None:
    """Resolve legacy/local public/private media to a safe local file path."""
    if not image_path:
        return None
    clean = image_path.lstrip("/")
    settings = get_settings(require_bot_token=False)
    root = Path(settings.data_dir).resolve()
    if clean.startswith(("uploads/", "private/")):
        p = (root / clean).resolve()
        if root not in p.parents:
            return None
        return p if p.exists() and p.is_file() else None
    p = Path(image_path).expanduser()
    return p if p.exists() and p.is_file() else None


async def load_file_bytes(db: Database, file_path: str | None) -> bytes | None:
    """Load stored bytes without exposing private media through a public URL."""
    if not file_path:
        return None
    if file_path.startswith("/media/"):
        try:
            asset_id = int(file_path.rstrip("/").split("/")[-1])
        except ValueError:
            return None
        async with db.session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            if not asset or asset.lifecycle_state == "deleted":
                return None
            return await read_media_asset_bytes(db, asset)
    p = media_file(file_path)
    if not p:
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


async def load_image_bytes(db: Database, image_path: str | None) -> bytes | None:
    return await load_file_bytes(db, image_path)


async def telegram_photo_input(db: Database, image_path: str | None):
    """Return aiogram input without exposing private media over HTTP."""
    if not image_path:
        return None
    if image_path.startswith("/media/"):
        try:
            asset_id = int(image_path.rstrip("/").split("/")[-1])
        except ValueError:
            return None
        async with db.session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            if not asset or asset.lifecycle_state == "deleted":
                return None
            data = await read_media_asset_bytes(db, asset)
            if not data:
                return None
            return BufferedInputFile(data, filename=asset.filename or "image")
    p = media_file(image_path)
    return FSInputFile(p) if p else None


async def save_telegram_photo(bot: Bot, file_id: str, category: str, db: Database, *, max_mb: int = 20) -> str:
    tg_file = await bot.get_file(file_id)
    buffer = BytesIO()
    await bot.download_file(tg_file.file_path, destination=buffer)
    raw = buffer.getvalue()
    if len(raw) > max_mb * 1024 * 1024:
        raise ValueError(f"Фото завелике. Максимум — {max_mb} МБ.")
    return await store_image_bytes(db, raw, category, original_name=tg_file.file_path or "telegram-photo")


async def verify_media_asset(db: Database, asset_id: int) -> dict[str, object]:
    """Verify one canonical MediaAsset against size, MIME and checksum metadata."""
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            return {"ok": False, "reason": "missing_asset"}
        data = await read_media_asset_bytes(db, asset)
        if data is None:
            asset.integrity_status = "missing"
            await session.commit()
            return {"ok": False, "reason": "missing_object"}
        actual_checksum = checksum_bytes(data)
        detected = sniff_mime(data, asset.filename)
        if asset.checksum_sha256 and actual_checksum != asset.checksum_sha256:
            asset.integrity_status = "corrupt"
            await session.commit()
            return {"ok": False, "reason": "checksum_mismatch", "checksum": actual_checksum}
        asset.checksum_sha256 = actual_checksum
        asset.detected_mime = detected
        asset.size_bytes = len(data)
        asset.integrity_status = "ok"
        asset.last_verified_at = clock.storage_utc()
        await session.commit()
        return {"ok": True, "checksum": actual_checksum, "mime": detected, "size": len(data)}
