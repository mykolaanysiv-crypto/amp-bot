from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile
from PIL import Image, ImageOps
from sqlalchemy import delete

from .config import get_settings
from .db import Database
from .models import MediaAsset
from .security import media_access_level


def normalize_image_bytes(raw: bytes) -> bytes:
    """Normalize an uploaded image to a compact WebP without cropping."""
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


def _local_storage_folder(category: str) -> tuple[str, Path]:
    settings = get_settings(require_bot_token=False)
    level = media_access_level(category)
    root_name = "uploads" if level == "public" else "private"
    folder = Path(settings.data_dir) / root_name / category
    folder.mkdir(parents=True, exist_ok=True)
    return root_name, folder


async def store_image_bytes(db: Database, raw: bytes, category: str, *, original_name: str = "image") -> str:
    """Store normalized media persistently with secure-by-default local paths."""
    settings = get_settings(require_bot_token=False)
    normalized = normalize_image_bytes(raw)
    filename = f"{uuid4().hex}.webp"

    if settings.media_storage == "database":
        async with db.session_factory() as session:
            asset = MediaAsset(
                category=category,
                filename=filename,
                content_type="image/webp",
                data=normalized,
                size_bytes=len(normalized),
            )
            session.add(asset)
            await session.flush()
            asset_id = asset.id
            await session.commit()
        return f"/media/{asset_id}"

    root_name, folder = _local_storage_folder(category)
    out = folder / filename
    out.write_bytes(normalized)
    return f"/{root_name}/{category}/{filename}"


def normalize_transparent_png_bytes(raw: bytes) -> bytes:
    """Normalize an ambassador badge artwork while preserving alpha transparency."""
    try:
        img = Image.open(BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGBA")
        img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, "PNG", optimize=True)
        return output.getvalue()
    except Exception as exc:
        raise ValueError("Не вдалося обробити PNG. Завантажте коректне PNG-зображення.") from exc


async def store_transparent_png(db: Database, raw: bytes, category: str, *, original_name: str = "badge.png") -> str:
    settings = get_settings(require_bot_token=False)
    normalized = normalize_transparent_png_bytes(raw)
    filename = f"{uuid4().hex}.png"
    if settings.media_storage == "database":
        async with db.session_factory() as session:
            asset = MediaAsset(category=category, filename=filename, content_type="image/png", data=normalized, size_bytes=len(normalized))
            session.add(asset)
            await session.flush()
            asset_id = asset.id
            await session.commit()
        return f"/media/{asset_id}"
    root_name, folder = _local_storage_folder(category)
    out = folder / filename
    out.write_bytes(normalized)
    return f"/{root_name}/{category}/{filename}"


async def store_file_bytes(db: Database, raw: bytes, category: str, *, original_name: str = "file", content_type: str = "application/octet-stream") -> str:
    """Store an arbitrary file. Non-public categories never live under /uploads."""
    settings = get_settings(require_bot_token=False)
    suffix = Path(original_name or "file").suffix.lower()[:10]
    filename = f"{uuid4().hex}{suffix}"
    if settings.media_storage == "database":
        async with db.session_factory() as session:
            asset = MediaAsset(category=category, filename=filename, content_type=content_type or "application/octet-stream", data=raw, size_bytes=len(raw))
            session.add(asset)
            await session.flush()
            asset_id = asset.id
            await session.commit()
        return f"/media/{asset_id}"
    root_name, folder = _local_storage_folder(category)
    out = folder / filename
    out.write_bytes(raw)
    return f"/{root_name}/{category}/{filename}"


async def delete_stored_image(db: Database, image_path: str | None) -> None:
    if not image_path:
        return
    if image_path.startswith("/media/"):
        try:
            asset_id = int(image_path.rstrip("/").split("/")[-1])
        except ValueError:
            return
        async with db.session_factory() as session:
            await session.execute(delete(MediaAsset).where(MediaAsset.id == asset_id))
            await session.commit()
        return

    if image_path.startswith(("/uploads/", "/private/")):
        settings = get_settings(require_bot_token=False)
        fp = Path(settings.data_dir) / image_path.lstrip("/")
        try:
            if fp.exists():
                fp.unlink()
        except OSError:
            pass


def media_file(image_path: str | None) -> Path | None:
    """Resolve local public/private media to a safe local file path."""
    if not image_path:
        return None
    clean = image_path.lstrip("/")
    settings = get_settings(require_bot_token=False)
    root = Path(settings.data_dir).resolve()
    if clean.startswith(("uploads/", "private/")):
        p = (root / clean).resolve()
        if root not in p.parents:
            return None
        return p if p.exists() else None
    p = Path(image_path).expanduser()
    return p if p.exists() else None


async def load_file_bytes(db: Database, file_path: str | None) -> bytes | None:
    """Load arbitrary stored file bytes without routing through HTTP."""
    if not file_path:
        return None
    if file_path.startswith("/media/"):
        try:
            asset_id = int(file_path.rstrip("/").split("/")[-1])
        except ValueError:
            return None
        async with db.session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            return bytes(asset.data) if asset and asset.data is not None else None
    p = media_file(file_path)
    if not p:
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


async def load_image_bytes(db: Database, image_path: str | None) -> bytes | None:
    """Load stored image bytes without going through a public HTTP URL."""
    if not image_path:
        return None
    if image_path.startswith("/media/"):
        try:
            asset_id = int(image_path.rstrip("/").split("/")[-1])
        except ValueError:
            return None
        async with db.session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            return bytes(asset.data) if asset and asset.data else None
    p = media_file(image_path)
    if not p:
        return None
    try:
        return p.read_bytes()
    except OSError:
        return None


async def telegram_photo_input(db: Database, image_path: str | None):
    """Return an aiogram input without exposing private DB media over HTTP.

    Database-backed media are sent as bytes. Local media are sent directly from
    disk. This allows /media and /private routes to remain access-controlled.
    """
    if not image_path:
        return None
    if image_path.startswith("/media/"):
        try:
            asset_id = int(image_path.rstrip("/").split("/")[-1])
        except ValueError:
            return None
        async with db.session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            if not asset or not asset.data:
                return None
            filename = asset.filename or "image"
            return BufferedInputFile(bytes(asset.data), filename=filename)
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
