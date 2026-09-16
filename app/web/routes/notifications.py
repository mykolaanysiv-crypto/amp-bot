from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select

from app.web.dependencies import (
    HTMLResponse, Notification, Request, User, ctx, db, guard, log_audit, templates
)

router = APIRouter()

NOTIFICATION_FILTERS = [
    ("system", "Системні"),
    ("event", "Події"),
    ("broadcast", "Розсилки"),
    ("case", "Кейси"),
    ("streak", "Серії участі"),
    ("survey", "Опитування"),
]


@router.get("/admin/notifications", response_class=HTMLResponse)
async def notifications_center(request: Request, type: str = "", status: str = "", q: str = ""):
    if r := guard(request):
        return r
    type = (type or "").strip()
    status = (status or "").strip()
    q = (q or "").strip()
    async with db.session_factory() as session:
        kpi = {
            "queued": int(await session.scalar(select(func.count(Notification.id)).where(Notification.status.in_(["queued", "retry"]))) or 0),
            "sent": int(await session.scalar(select(func.count(Notification.id)).where(Notification.status == "sent")) or 0),
            "failed": int(await session.scalar(select(func.count(Notification.id)).where(Notification.status == "failed")) or 0),
        }
        stmt = select(Notification).order_by(Notification.created_at.desc(), Notification.id.desc())
        if type:
            stmt = stmt.where(Notification.type == type)
        if status:
            if status == "queued":
                stmt = stmt.where(Notification.status.in_(["queued", "retry"]))
            else:
                stmt = stmt.where(Notification.status == status)
        if q:
            needle = f"%{q}%"
            stmt = stmt.where(or_(Notification.title.ilike(needle), Notification.body.ilike(needle)))
        rows = list((await session.scalars(stmt.limit(300))).all())
        users = {}
        ids = sorted({int(row.recipient_user_id) for row in rows if row.recipient_user_id})
        if ids:
            users = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(ids)))).all()}
    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context=ctx(request, rows=rows, users=users, kpi=kpi, filters=NOTIFICATION_FILTERS, filter_type=type, filter_status=status, q=q),
    )


@router.post("/admin/notifications/retry-failed")
async def notifications_retry_failed(request: Request):
    if r := guard(request):
        return r
    now = clock.storage_utc()
    async with db.session_factory() as session:
        rows = list((await session.scalars(select(Notification).where(Notification.status == "failed").limit(1000))).all())
        for row in rows:
            row.status = "retry"
            row.retry_count = 0
            row.error = ""
            row.scheduled_at = now
            row.updated_at = now
        await log_audit(session, "notification_center_retry_failed", actor_label=request.session.get("admin_name", "web"), entity_type="notification", details=f"Повторно поставлено в чергу: {len(rows)}")
        await session.commit()
    return RedirectResponse("/admin/notifications?status=queued", status_code=303)
