from __future__ import annotations
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from app.governance import SEVERITY_ORDER, scan_operational_issues
from app.model_domains import OperationalIssue
from app.time_utils import clock
from app.web.dependencies import ctx, db, guard_superadmin, log_audit, templates

router=APIRouter()

@router.get('/admin/operations',response_class=HTMLResponse)
async def operations_page(request:Request,status:str='open'):
    if r:=guard_superadmin(request): return r
    async with db.session_factory() as session:
        await scan_operational_issues(session)
        await session.commit()
        stmt=select(OperationalIssue)
        if status in {'open','resolved'}: stmt=stmt.where(OperationalIssue.status==status)
        rows=list((await session.scalars(stmt.order_by(OperationalIssue.last_seen_at.desc()))).all())
        rows.sort(key=lambda x:(SEVERITY_ORDER.get(x.severity,9),-x.last_seen_at.timestamp()))
        counts={'open':sum(1 for r in rows if r.status=='open'),'resolved':sum(1 for r in rows if r.status=='resolved')}
        return templates.TemplateResponse(request=request,name='operations.html',context=ctx(request,rows=rows,status=status,counts=counts))


@router.post('/admin/operations/{issue_id}/assign')
async def assign_issue(request:Request,issue_id:int,assignee_label:str=Form('')):
    if r:=guard_superadmin(request): return r
    async with db.session_factory() as session:
        row=await session.get(OperationalIssue,issue_id)
        if row:
            row.assignee_label=(assignee_label or '').strip()[:160]
            await log_audit(session,'operational_issue_assigned',actor_label=request.session.get('admin_name','superadmin'),entity_type='operational_issue',entity_id=row.id,details=f'assignee={row.assignee_label or "—"}')
            await session.commit()
    return RedirectResponse('/admin/operations',303)

@router.post('/admin/operations/{issue_id}/resolve')
async def resolve_issue(request:Request,issue_id:int,resolution_note:str=Form('')):
    if r:=guard_superadmin(request): return r
    async with db.session_factory() as session:
        row=await session.get(OperationalIssue,issue_id)
        if row:
            row.status='resolved'; row.resolved_at=clock.storage_utc(); row.resolved_by=request.session.get('admin_name','superadmin'); row.resolution_note=(resolution_note or '').strip()
            await log_audit(session,'operational_issue_resolved',actor_label=row.resolved_by,entity_type='operational_issue',entity_id=row.id,details=f'{row.issue_type}: {row.resolution_note}')
            await session.commit()
    return RedirectResponse('/admin/operations',303)

@router.post('/admin/operations/{issue_id}/reopen')
async def reopen_issue(request:Request,issue_id:int):
    if r:=guard_superadmin(request): return r
    async with db.session_factory() as session:
        row=await session.get(OperationalIssue,issue_id)
        if row:
            row.status='open'; row.resolved_at=None; row.resolved_by=None; row.resolution_note=''
            await log_audit(session,'operational_issue_reopened',actor_label=request.session.get('admin_name','superadmin'),entity_type='operational_issue',entity_id=row.id,details=row.issue_type)
            await session.commit()
    return RedirectResponse('/admin/operations?status=resolved',303)
