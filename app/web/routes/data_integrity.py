from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.data_integrity import scan_data_integrity
from app.privacy_retention import cleanup_retained_data
from app.web.dependencies import ctx, db, guard_superadmin, log_audit, process_event_operations, settings, templates

router = APIRouter()


@router.get("/admin/data-integrity", response_class=HTMLResponse)
async def data_integrity_center(request: Request, notice: str = ""):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        report = await scan_data_integrity(session)
        await log_audit(
            session, "web_data_integrity_scan", actor_label=request.session.get("admin_name", "web"),
            entity_type="system", details=f"groups={report['issue_groups']}; affected={report['affected']}",
        )
        await session.commit()
    return templates.TemplateResponse(
        request=request,
        name="data_integrity.html",
        context=ctx(request, report=report, notice=notice),
    )


@router.post("/admin/data-integrity/retention-cleanup")
async def data_integrity_retention_cleanup(request: Request):
    if r := guard_superadmin(request):
        return r
    summary = await cleanup_retained_data(db, settings, actor_label=request.session.get("admin_name", "web"))
    return RedirectResponse(f"/admin/data-integrity?notice=retention:{summary.total}", status_code=303)


@router.post("/admin/data-integrity/refresh-event-operations")
async def data_integrity_refresh_events(request: Request):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        changed = await process_event_operations(session)
        await log_audit(
            session, "web_data_integrity_event_refresh", actor_label=request.session.get("admin_name", "web"),
            entity_type="system", details=str(changed),
        )
        await session.commit()
    count = sum(int(v or 0) for v in changed.values())
    return RedirectResponse(f"/admin/data-integrity?notice=events:{count}", status_code=303)
