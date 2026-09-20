from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .dependencies import db, is_superadmin, logged_in, log_audit, media_access_level, settings
from ..model_domains import MediaAsset

router = APIRouter()

@router.get("/media/{asset_id}")
async def media_asset(request: Request, asset_id: int):
    """Serve DB media according to explicit access classification.

    Public artwork is cacheable. Evidence, case attachments and documents are
    never exposed to anonymous direct URLs. Sensitive views are audited.
    """
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Файл не знайдено")
        level = media_access_level(asset.category)
        if level != "public":
            if not logged_in(request):
                raise HTTPException(status_code=404, detail="Файл не знайдено")
            if level == "superadmin_private" and not is_superadmin(request):
                raise HTTPException(status_code=404, detail="Файл не знайдено")
            await log_audit(
                session,
                "web_sensitive_media_view",
                actor_label=request.session.get("admin_name", "web"),
                entity_type="media_asset",
                entity_id=asset.id,
                details=f"category={asset.category}; access={level}",
            )
            await session.commit()
        return Response(
            content=asset.data,
            media_type=asset.content_type or "application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=86400" if level == "public" else "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


@router.get("/uploads/{category}/{filename}")
async def categorized_upload_file(request: Request, category: str, filename: str):
    """Serve legacy/local uploads through the same category access policy.

    This intentionally replaces the old public StaticFiles /uploads mount so
    historic request/evidence files can no longer be fetched anonymously.
    """
    level = media_access_level(category)
    if level != "public":
        if not logged_in(request):
            raise HTTPException(status_code=404, detail="Файл не знайдено")
        if level == "superadmin_private" and not is_superadmin(request):
            raise HTTPException(status_code=404, detail="Файл не знайдено")
    root = (Path(settings.data_dir) / "uploads" / category).resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    content_type = {
        ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    if level != "public":
        async with db.session_factory() as session:
            await log_audit(
                session, "web_sensitive_media_view", actor_label=request.session.get("admin_name", "web"),
                entity_type="legacy_media", details=f"category={category}; file={filename}; access={level}",
            )
            await session.commit()
    return Response(
        content=path.read_bytes(), media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400" if level == "public" else "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/private/{category}/{filename}")
async def private_media_file(request: Request, category: str, filename: str):
    """Serve local-development private media through the same role policy."""
    level = media_access_level(category)
    if level == "public":
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    if not logged_in(request):
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    if level == "superadmin_private" and not is_superadmin(request):
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    root = (Path(settings.data_dir) / "private" / category).resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    content_type = {
        ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    async with db.session_factory() as session:
        await log_audit(
            session, "web_sensitive_media_view", actor_label=request.session.get("admin_name", "web"),
            entity_type="private_media", details=f"category={category}; file={filename}; access={level}",
        )
        await session.commit()
    return Response(
        content=path.read_bytes(), media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
