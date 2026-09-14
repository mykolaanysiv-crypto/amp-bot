from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/analytics", response_class=HTMLResponse)
async def analytics_dashboard(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    return templates.TemplateResponse(
        request=request, name="analytics.html",
        context=ctx(request, analytics=data, metric_meta=METRIC_META)
    )


@router.get("/admin/analytics/export.xlsx")
async def analytics_export_excel(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    payload = analytics_excel(data)
    filename = "AMP_analytics_%s.xlsx" % data["generated_at"].strftime("%Y-%m-%d")
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/analytics/export.pdf")
async def analytics_export_pdf(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    payload = analytics_pdf(data)
    filename = "AMP_analytics_%s.pdf" % data["generated_at"].strftime("%Y-%m-%d")
    return Response(content=payload, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/admin/analytics/export.png")
async def analytics_export_png(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    payload = analytics_png(data)
    filename = "AMP_analytics_%s.png" % data["generated_at"].strftime("%Y-%m-%d")
    return Response(content=payload, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/admin/analytics/{metric_key}", response_class=HTMLResponse)
async def analytics_detail(request: Request, metric_key: str):
    if r := guard(request): return r
    if metric_key not in METRIC_META:
        raise HTTPException(status_code=404, detail="Аналітичний показник не знайдено")
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    metric = data["metrics"][metric_key]
    return templates.TemplateResponse(
        request=request, name="analytics_detail.html",
        context=ctx(request, analytics=data, metric=metric)
    )


@router.get("/admin/analytics/{metric_key}/export.xlsx")
async def analytics_metric_export_excel(request: Request, metric_key: str):
    if r := guard(request): return r
    if metric_key not in METRIC_META:
        raise HTTPException(status_code=404, detail="Аналітичний показник не знайдено")
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    payload = analytics_excel(data, metric_key)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="AMP_analytics_{metric_key}.xlsx"'},
    )


@router.get("/admin/analytics/{metric_key}/export.pdf")
async def analytics_metric_export_pdf(request: Request, metric_key: str):
    if r := guard(request): return r
    if metric_key not in METRIC_META:
        raise HTTPException(status_code=404, detail="Аналітичний показник не знайдено")
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    payload = analytics_pdf(data, metric_key)
    return Response(
        content=payload, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="AMP_analytics_{metric_key}.pdf"'},
    )


@router.get("/admin/analytics/{metric_key}/export.png")
async def analytics_metric_export_png(request: Request, metric_key: str):
    if r := guard(request): return r
    if metric_key not in METRIC_META:
        raise HTTPException(status_code=404, detail="Аналітичний показник не знайдено")
    async with db.session_factory() as session:
        data = await build_analytics(session, reveal_sensitive_counts=is_superadmin(request))
    payload = analytics_png(data, metric_key)
    return Response(content=payload, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="AMP_analytics_{metric_key}.png"'})

