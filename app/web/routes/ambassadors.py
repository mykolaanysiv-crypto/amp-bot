from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.ambassadors import AMBASSADOR_RESPONSIBILITIES, responsibility_label
from app.models import AmbassadorReport, User, UserRole
from app.time_utils import clock
from app.web.dependencies import ctx, db, guard, log_audit, templates, web_role

router = APIRouter()


def _guard_admin_superadmin(request: Request):
    if r := guard(request):
        return r
    if web_role(request) not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        return HTMLResponse("<h1>403</h1><p>Кабінети АМПасадорів доступні лише адміністратору та суперадміністратору.</p>", status_code=403)
    return None


@router.get("/admin/ambassadors", response_class=HTMLResponse)
async def ambassadors_page(request: Request):
    if r := _guard_admin_superadmin(request):
        return r
    async with db.session_factory() as session:
        ambassadors = list((await session.scalars(
            select(User).where(User.role == UserRole.AMBASSADOR.value).order_by(User.full_name.asc())
        )).all())
        report_rows = list((await session.execute(
            select(AmbassadorReport, User)
            .join(User, User.id == AmbassadorReport.user_id)
            .order_by(AmbassadorReport.created_at.desc())
        )).all())
    return templates.TemplateResponse(
        request=request,
        name="ambassadors.html",
        context=ctx(request, ambassadors=ambassadors, report_rows=report_rows,
                    responsibilities=AMBASSADOR_RESPONSIBILITIES, responsibility_label=responsibility_label),
    )


@router.post("/admin/ambassadors/{user_id}/responsibility")
async def ambassador_responsibility_update(request: Request, user_id: int, responsibility: str = Form("")):
    if r := _guard_admin_superadmin(request):
        return r
    value = responsibility.strip()
    if value and value not in AMBASSADOR_RESPONSIBILITIES:
        raise HTTPException(status_code=400, detail="Некоректний напрям відповідальності.")
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user or user.role != UserRole.AMBASSADOR.value:
            raise HTTPException(status_code=404, detail="АМПасадора не знайдено.")
        previous = user.ambassador_responsibility
        user.ambassador_responsibility = value or None
        await log_audit(session, "web_ambassador_responsibility_update", actor_label=request.session.get("admin_name", "web"),
                        entity_type="user", entity_id=user.id, details=f"{previous or '—'} -> {value or '—'}")
        await session.commit()
    return RedirectResponse("/admin/ambassadors#team", status_code=303)


@router.post("/admin/ambassadors/reports/{report_id}/review")
async def ambassador_report_review(request: Request, report_id: int, admin_note: str = Form("")):
    if r := _guard_admin_superadmin(request):
        return r
    async with db.session_factory() as session:
        row = await session.get(AmbassadorReport, report_id)
        if not row:
            raise HTTPException(status_code=404, detail="Звіт не знайдено.")
        row.status = "reviewed"
        row.admin_note = admin_note.strip()[:3000]
        row.reviewed_at = clock.storage_utc()
        row.reviewed_by = request.session.get("admin_name", "web")[:160]
        await log_audit(session, "web_ambassador_report_review", actor_label=request.session.get("admin_name", "web"),
                        entity_type="ambassador_report", entity_id=row.id, details=f"user_id={row.user_id}")
        await session.commit()
    return RedirectResponse("/admin/ambassadors#reports", status_code=303)
