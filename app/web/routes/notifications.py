from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import func, or_, select, exists
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.web.dependencies import (
    HTMLResponse, Notification, Request, User, ctx, db, guard, log_audit, templates, WebStaffAccount

)

from app.model_domains import WebNotificationRead

router = APIRouter()


async def _web_inbox_query(session, request):
    """Only records addressed to the staff account's linked participant identity."""
    account_id = request.session.get("admin_account_id")
    if not account_id:
        raise HTTPException(status_code=403)
    account = await session.get(WebStaffAccount, int(account_id))
    if account is None or not account.active:
        raise HTTPException(status_code=403)
    if not account.linked_user_id:
        return account.id, None
    read = exists(select(WebNotificationRead.id).where(
        WebNotificationRead.account_id == account.id,
        WebNotificationRead.notification_id == Notification.id,
    ))
    return account.id, select(Notification).where(Notification.recipient_user_id == account.linked_user_id, ~read)


@router.get("/admin/web-inbox/count")
async def web_inbox_count(request: Request):
    if response := guard(request):
        return response
    async with db.session_factory() as session:
        _, query = await _web_inbox_query(session, request)
        count = int(await session.scalar(select(func.count()).select_from(query.subquery())) or 0) if query is not None else 0
    return JSONResponse({"unread": count}, headers={"Cache-Control": "no-store"})


@router.get("/admin/web-inbox", response_class=HTMLResponse)
async def web_inbox(request: Request):
    if response := guard(request):
        return response
    async with db.session_factory() as session:
        account_id, query = await _web_inbox_query(session, request)
        rows = list((await session.scalars(query.order_by(Notification.created_at.desc()).limit(100))).all()) if query is not None else []
    return templates.TemplateResponse(request=request, name="web_inbox.html", context=ctx(request, rows=rows, linked=query is not None))


@router.post("/admin/web-inbox/read-all")
async def web_inbox_mark_all_read(request: Request):
    """Bulk mark only this account's linked participant messages, never global delivery state."""
    if response := guard(request):
        return response
    async with db.session_factory() as session:
        account_id, query = await _web_inbox_query(session, request)
        if query is not None:
            stmt = pg_insert(WebNotificationRead).from_select(
                ["account_id", "notification_id"],
                select(func.cast(account_id, WebNotificationRead.account_id.type), Notification.id).where(
                    Notification.recipient_user_id == (
                        select(WebStaffAccount.linked_user_id).where(WebStaffAccount.id == account_id).scalar_subquery()
                    ),
                    ~exists(select(WebNotificationRead.id).where(
                        WebNotificationRead.account_id == account_id,
                        WebNotificationRead.notification_id == Notification.id,
                    )),
                ),
            )
            await session.execute(stmt.on_conflict_do_nothing(constraint="uq_web_notification_read"))
            await session.commit()
    return RedirectResponse("/admin/web-inbox", status_code=303)


@router.post("/admin/web-inbox/{notification_id}/read")
async def web_inbox_mark_read(request: Request, notification_id: int):
    if response := guard(request):
        return response
    if notification_id <= 0:
        raise HTTPException(status_code=404)
    async with db.session_factory() as session:
        account_id, query = await _web_inbox_query(session, request)
        if query is None or not await session.scalar(query.where(Notification.id == notification_id)):
            raise HTTPException(status_code=404)
        session.add(WebNotificationRead(account_id=account_id, notification_id=notification_id))
        await session.commit()
    return RedirectResponse("/admin/web-inbox", status_code=303)


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
        # Single aggregation replaces three separate table scans/round trips.
        grouped_status = (await session.execute(
            select(Notification.status, func.count(Notification.id)).group_by(Notification.status)
        )).all()
        status_counts = {str(status): int(count) for status, count in grouped_status}
        kpi = {
            "queued": status_counts.get("queued", 0) + status_counts.get("retry", 0),
            "sent": status_counts.get("sent", 0),
            "failed": status_counts.get("failed", 0),
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
