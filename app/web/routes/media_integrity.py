from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete

from app.media_integrity import media_reference_count, scan_media_integrity
from app.media_storage import get_media_storage
from app.model_domains import MediaAsset
from app.time_utils import clock
from app.web.dependencies import ctx, db, guard_superadmin, log_audit, templates

router = APIRouter()


@router.get('/admin/media-integrity', response_class=HTMLResponse)
async def media_integrity_center(request: Request, deep: int = 0, notice: str = ''):
    if r := guard_superadmin(request):
        return r
    report = await scan_media_integrity(db, deep=bool(deep))
    async with db.session_factory() as session:
        await log_audit(
            session,
            'web_media_integrity_scan',
            actor_label=request.session.get('admin_name', 'web'),
            entity_type='media',
            details=f"total={report['total_media']}; deep={bool(deep)}; orphan={len(report['orphan_ids'])}; missing={len(report['missing_ids'])}",
        )
        await session.commit()
    return templates.TemplateResponse(
        request=request,
        name='media_integrity.html',
        context=ctx(request, report=report, notice=notice),
    )


async def _asset_or_404(asset_id: int):
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail='MediaAsset не знайдено')
        return asset


@router.post('/admin/media-integrity/{asset_id}/candidate')
async def media_candidate(request: Request, asset_id: int):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail='MediaAsset не знайдено')
        if asset.lifecycle_state == 'deleted':
            raise HTTPException(status_code=409, detail='Файл уже видалено')
        asset.lifecycle_state = 'candidate'
        asset.integrity_status = 'pending_review'
        await log_audit(session, 'media_lifecycle_candidate', actor_label=request.session.get('admin_name', 'web'), entity_type='media_asset', entity_id=asset.id)
        await session.commit()
    return RedirectResponse('/admin/media-integrity?notice=candidate', status_code=303)


@router.post('/admin/media-integrity/{asset_id}/review')
async def media_review(request: Request, asset_id: int):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail='MediaAsset не знайдено')
        if asset.lifecycle_state not in {'candidate', 'active'}:
            raise HTTPException(status_code=409, detail='Спочатку файл має бути активним або кандидатом')
        asset.lifecycle_state = 'reviewed'
        asset.reviewed_at = clock.storage_utc()
        await log_audit(session, 'media_lifecycle_reviewed', actor_label=request.session.get('admin_name', 'web'), entity_type='media_asset', entity_id=asset.id)
        await session.commit()
    return RedirectResponse('/admin/media-integrity?notice=reviewed', status_code=303)


@router.post('/admin/media-integrity/{asset_id}/quarantine')
async def media_quarantine(request: Request, asset_id: int):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail='MediaAsset не знайдено')
        if asset.lifecycle_state != 'reviewed':
            raise HTTPException(status_code=409, detail='Перед карантином потрібна ручна перевірка')
        asset.lifecycle_state = 'quarantine'
        asset.quarantined_at = clock.storage_utc()
        await log_audit(session, 'media_lifecycle_quarantine', actor_label=request.session.get('admin_name', 'web'), entity_type='media_asset', entity_id=asset.id)
        await session.commit()
    return RedirectResponse('/admin/media-integrity?notice=quarantine', status_code=303)


@router.post('/admin/media-integrity/{asset_id}/delete')
async def media_hard_delete(request: Request, asset_id: int, confirmation: str = Form(...)):
    if r := guard_superadmin(request):
        return r
    if confirmation.strip().upper() != 'ВИДАЛИТИ':
        raise HTTPException(status_code=400, detail='Для остаточного видалення введіть ВИДАЛИТИ')
    async with db.session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail='MediaAsset не знайдено')
        if asset.lifecycle_state != 'quarantine' or not asset.quarantined_at:
            raise HTTPException(status_code=409, detail='Hard-delete дозволено лише після review → quarantine')
        refs = await media_reference_count(session, asset.id)
        if refs:
            raise HTTPException(status_code=409, detail=f'Файл ще має активні посилання: {refs}')
        storage = get_media_storage(asset.storage_backend or 'database')
        await storage.delete_asset_object(db, asset)
        await log_audit(session, 'media_lifecycle_hard_delete', actor_label=request.session.get('admin_name', 'web'), entity_type='media_asset', entity_id=asset.id, details=f'backend={asset.storage_backend}; checksum={asset.checksum_sha256 or "unknown"}')
        await session.execute(delete(MediaAsset).where(MediaAsset.id == asset.id))
        await session.commit()
    return RedirectResponse('/admin/media-integrity?notice=deleted', status_code=303)
