from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.ambassadors import AMP_TEAM_ROLES, AMBASSADOR_RESPONSIBILITIES, responsibility_label
from app.model_domains import AmbassadorReport, TeamTask, User, UserRole, UserStatus
from app.reliability import queue_telegram_delivery
from app.domain_services import add_xp
from app.time_utils import clock
from app.ui_labels import label
from app.web.dependencies import ctx, db, guard, log_audit, templates, web_role

router = APIRouter()


def _guard_admin_superadmin(request: Request):
    if r := guard(request):
        return r
    if web_role(request) not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        return HTMLResponse("<h1>403</h1><p>Керування командою АМП доступне лише адміністратору та суперадміністратору.</p>", status_code=403)
    return None


def _parse_deadline(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некоректний дедлайн завдання.") from exc


@router.get("/admin/ambassadors", response_class=HTMLResponse)
async def ambassadors_page(request: Request):
    if r := _guard_admin_superadmin(request):
        return r
    async with db.session_factory() as session:
        team_members = list((await session.scalars(
            select(User)
            .where(User.role.in_(AMP_TEAM_ROLES), User.status == UserStatus.ACTIVE.value)
            .order_by(User.role.asc(), User.full_name.asc())
        )).all())
        report_rows = list((await session.execute(
            select(AmbassadorReport, User)
            .join(User, User.id == AmbassadorReport.user_id)
            .where(User.role.in_(AMP_TEAM_ROLES))
            .order_by(AmbassadorReport.created_at.desc())
        )).all())
        task_rows = list((await session.execute(
            select(TeamTask, User)
            .join(User, User.id == TeamTask.assignee_user_id)
            .order_by(TeamTask.created_at.desc())
        )).all())
    return templates.TemplateResponse(
        request=request,
        name="ambassadors.html",
        context=ctx(
            request,
            team_members=team_members,
            report_rows=report_rows,
            task_rows=task_rows,
            responsibilities=AMBASSADOR_RESPONSIBILITIES,
            responsibility_label=responsibility_label,
            role_label=label,
        ),
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
        if not user or user.role not in AMP_TEAM_ROLES:
            raise HTTPException(status_code=404, detail="Учасника команди АМП не знайдено.")
        previous = user.ambassador_responsibility
        user.ambassador_responsibility = value or None
        await log_audit(
            session,
            "web_team_responsibility_update",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="user",
            entity_id=user.id,
            details=f"{previous or '—'} -> {value or '—'}",
        )
        await session.commit()
    return RedirectResponse("/admin/ambassadors#team", status_code=303)


@router.post("/admin/ambassadors/tasks/create")
async def team_task_create(
    request: Request,
    assignee_user_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    xp_reward: int = Form(10),
    deadline: str = Form(""),
):
    if r := _guard_admin_superadmin(request):
        return r
    clean_title = title.strip()
    if len(clean_title) < 3:
        raise HTTPException(status_code=400, detail="Назва завдання занадто коротка.")
    reward = max(0, min(500, int(xp_reward or 0)))
    due = _parse_deadline(deadline)
    async with db.session_factory() as session:
        user = await session.get(User, assignee_user_id)
        if not user or user.status != UserStatus.ACTIVE.value or user.role not in AMP_TEAM_ROLES:
            raise HTTPException(status_code=400, detail="Завдання можна призначити лише активному члену команди АМП.")
        task = TeamTask(
            assignee_user_id=user.id,
            title=clean_title[:180],
            description=description.strip()[:5000],
            xp_reward=reward,
            deadline=due,
            status="assigned",
            created_by_label=request.session.get("admin_name", "web")[:160],
            created_at=clock.storage_utc(),
            updated_at=clock.storage_utc(),
        )
        session.add(task)
        await session.flush()
        deadline_text = due.strftime("%d.%m.%Y %H:%M") if due else "без дедлайну"
        await queue_telegram_delivery(
            session,
            user.tg_id,
            f"🧭 <b>Нове завдання для команди АМП</b>\n\n<b>{task.title}</b>\n⚡ {task.xp_reward} XP\n📅 {deadline_text}\n\nДля завершення обов’язково подай звіт у Кабінеті команди.",
            source="team_task",
            dedupe_key=f"team_task_assigned:{task.id}",
            recipient_user_id=user.id,
            entity_type="team_task",
            entity_id=task.id,
            button_text="📋 Відкрити завдання",
            callback_data=f"teamtask:{task.id}",
        )
        await log_audit(
            session,
            "web_team_task_create",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="team_task",
            entity_id=task.id,
            details=f"assignee={user.id}; xp={reward}; {task.title}",
        )
        await session.commit()
    return RedirectResponse("/admin/ambassadors#tasks", status_code=303)


@router.post("/admin/ambassadors/tasks/{task_id}/review")
async def team_task_review(
    request: Request,
    task_id: int,
    action: str = Form(...),
    review_note: str = Form(""),
):
    if r := _guard_admin_superadmin(request):
        return r
    if action not in {"approve", "return", "cancel"}:
        raise HTTPException(status_code=400, detail="Некоректна дія із завданням.")
    async with db.session_factory() as session:
        task = await session.scalar(select(TeamTask).where(TeamTask.id == task_id).with_for_update())
        if not task:
            raise HTTPException(status_code=404, detail="Завдання не знайдено.")
        user = await session.get(User, task.assignee_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Виконавця не знайдено.")
        now = clock.storage_utc()
        note = review_note.strip()[:3000]
        if action == "approve":
            if task.status == "approved":
                return RedirectResponse("/admin/ambassadors#tasks", status_code=303)
            if task.status != "submitted" or not task.report_text.strip():
                raise HTTPException(status_code=409, detail="Спочатку учасник має подати обов’язковий звіт про виконання.")
            if task.xp_awarded_at is None and task.xp_reward > 0:
                await add_xp(
                    session,
                    user,
                    int(task.xp_reward),
                    f"Виконання командного завдання «{task.title}»",
                    category="team_task",
                )
                task.xp_awarded_at = now
            task.status = "approved"
            task.reviewed_at = now
            task.reviewed_by = request.session.get("admin_name", "web")[:160]
            task.review_note = note
            notice = f"✅ <b>Завдання підтверджено</b>\n\n<b>{task.title}</b>\nНараховано: <b>{task.xp_reward} XP</b>"
        elif action == "return":
            if task.status not in {"submitted", "returned"}:
                raise HTTPException(status_code=409, detail="Повернути можна лише поданий звіт.")
            task.status = "returned"
            task.reviewed_at = now
            task.reviewed_by = request.session.get("admin_name", "web")[:160]
            task.review_note = note
            notice = f"↩️ <b>Звіт повернуто на доопрацювання</b>\n\n<b>{task.title}</b>" + (f"\nКоментар: {note}" if note else "")
        else:
            if task.status == "approved":
                raise HTTPException(status_code=409, detail="Підтверджене завдання з уже нарахованим XP не можна скасувати.")
            task.status = "cancelled"
            task.reviewed_at = now
            task.reviewed_by = request.session.get("admin_name", "web")[:160]
            task.review_note = note
            notice = f"🚫 <b>Завдання скасовано</b>\n\n<b>{task.title}</b>" + (f"\nКоментар: {note}" if note else "")
        task.updated_at = now
        await queue_telegram_delivery(
            session,
            user.tg_id,
            notice,
            source="team_task",
            dedupe_key=f"team_task_{action}:{task.id}:{task.updated_at.isoformat()}",
            recipient_user_id=user.id,
            entity_type="team_task",
            entity_id=task.id,
            button_text="📋 Відкрити завдання",
            callback_data=f"teamtask:{task.id}",
        )
        await log_audit(
            session,
            f"web_team_task_{action}",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="team_task",
            entity_id=task.id,
            details=f"user={user.id}; note={note}",
        )
        await session.commit()
    return RedirectResponse("/admin/ambassadors#tasks", status_code=303)


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
        await log_audit(session, "web_team_report_review", actor_label=request.session.get("admin_name", "web"),
                        entity_type="ambassador_report", entity_id=row.id, details=f"user_id={row.user_id}")
        await session.commit()
    return RedirectResponse("/admin/ambassadors#reports", status_code=303)
