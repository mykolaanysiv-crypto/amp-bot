from __future__ import annotations
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from app.governance import SEVERITY_ORDER, scan_operational_issues
from app.model_domains import OperationalIssue, SystemSetting
from app.reliability import job_lock
from app.governance import SCAN_SETTING_KEY
from app.time_utils import clock
from app.web.dependencies import ctx, db, guard_superadmin, log_audit, templates

router=APIRouter()

@router.get('/admin/operations', response_class=HTMLResponse)
async def operations_page(request: Request, status: str = 'open', scan: str = ''):
    if r := guard_superadmin(request): return r
    async with db.session_factory() as session:
        counts = dict((await session.execute(
            select(OperationalIssue.status, func.count(OperationalIssue.id))
            .group_by(OperationalIssue.status)
        )).all())
        stmt = select(OperationalIssue)
        if status in {'open', 'resolved'}:
            stmt = stmt.where(OperationalIssue.status == status)
        rows = list((await session.scalars(stmt.order_by(
            OperationalIssue.last_seen_at.desc()))).all())
        rows.sort(key=lambda item: (
            SEVERITY_ORDER.get(item.severity, 9), -item.last_seen_at.timestamp()))
        marker = await session.get(SystemSetting, SCAN_SETTING_KEY)
        last_scan = ''
        if marker and marker.value:
            try:
                from datetime import datetime
                last_scan = clock.utc_to_local(
                    clock.from_storage_utc(datetime.fromisoformat(marker.value))
                ).strftime('%d.%m.%Y %H:%M')
            except (TypeError, ValueError):
                last_scan = 'невідомо'
        return templates.TemplateResponse(request=request, name='operations.html', context=ctx(
            request, rows=rows, status=status, scan=scan,
            counts={'open': counts.get('open', 0), 'resolved': counts.get('resolved', 0)},
            last_scan=last_scan))


@router.post('/admin/operations/scan')
async def scan_issues_manually(request: Request):
    if r := guard_superadmin(request): return r
    # Same distributed lock as the worker: no concurrent full table sweeps.
    async with job_lock(db, 'operational_scan', ttl_seconds=600) as acquired:
        if not acquired:
            return RedirectResponse('/admin/operations?scan=busy', 303)
        async with db.session_factory() as session:
            seen = await scan_operational_issues(session)
            await log_audit(session, 'operational_scan_manual',
                actor_label=request.session.get('admin_name', 'superadmin'),
                entity_type='system', details=f'Актуальних сигналів: {seen}')
            await session.commit()
    return RedirectResponse('/admin/operations?scan=ok', 303)


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
