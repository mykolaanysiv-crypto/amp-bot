from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.security_center import build_security_center_snapshot
from app.web.dependencies import ctx, db, guard_permission, log_audit, settings, templates

router = APIRouter()


@router.get("/admin/security-center", response_class=HTMLResponse)
async def security_center(request: Request):
    if r := guard_permission(request, "security.manage"):
        return r
    async with db.session_factory() as session:
        snapshot = await build_security_center_snapshot(session, db, settings)
        await log_audit(
            session,
            "web_security_center_view",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="system",
            details="Security Center viewed; no secret values exposed",
        )
        await session.commit()
    return templates.TemplateResponse(
        request=request,
        name="security_center.html",
        context=ctx(request, snapshot=snapshot),
    )
