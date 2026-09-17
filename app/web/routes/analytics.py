from __future__ import annotations

from fastapi import APIRouter
from app.web.dependencies import (
    HTMLResponse, HTTPException, METRIC_META, Request, Response, analytics_excel, analytics_pdf, analytics_png, build_analytics, ctx, db, guard, is_superadmin, templates
)
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
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
    scope_groups = {"age", "gender", "settlement", "vulnerability", "leagues", "lifecycle", "restoration"}
    scope_answers = {"event_outcomes", "surveys_weekly"}
    scope_periods = {"new_participants", "retention", "activity", "visits", "avg_attendance", "badges_weekly"}
    if metric_key in scope_groups:
        data_scope = "Агрегована група учасників"
    elif metric_key in scope_answers:
        data_scope = "Агреговані відповіді / результати"
    elif metric_key in scope_periods:
        data_scope = "Агрегований період"
    else:
        data_scope = "Агрегована категорія / тип"
    return templates.TemplateResponse(
        request=request, name="analytics_detail.html",
        context=ctx(request, analytics=data, metric=metric, analytics_data_scope=data_scope)
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

