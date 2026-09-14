from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    if r := guard(request): return r
    return templates.TemplateResponse(request=request, name="reports.html", context=ctx(request, current_year=datetime.now().year))


@router.get("/admin/reports/download")
async def reports_download(
    request: Request, period_type: str = "month", year: int = 2026, month: int = 1,
    start_month: int = 1, end_month: int = 12, quarter: int = 1, format: str = "pdf",
):
    if r := guard(request): return r
    try:
        start, end, period_label = resolve_report_period(period_type, year=year, month=month, start_month=start_month, end_month=end_month, quarter=quarter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with db.session_factory() as session:
        data = await build_period_report(session, start, end, period_label)
        await log_audit(session, "web_period_report", actor_label=request.session.get("admin_name","web"), entity_type="report", details=f"{period_label}; format={format}")
        await session.commit()
    safe = f"{year}_{period_type}"
    if format.lower() == "xlsx":
        return Response(content=report_excel(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="AMP_report_{safe}.xlsx"'})
    return Response(content=report_pdf(data), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="AMP_report_{safe}.pdf"'})

