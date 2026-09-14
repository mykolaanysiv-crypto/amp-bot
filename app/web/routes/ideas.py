from __future__ import annotations

from fastapi import APIRouter
from app.ui_labels import IDEA_STATUSES
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

async def _award_idea_approval_xp(session, idea: Idea) -> tuple[int | None, str]:
    return await award_idea_approval_once(session, idea)


@router.get("/admin/ideas", response_class=HTMLResponse)
async def ideas(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "workflow"):
    if r := guard(request): return r
    selected = status or request.query_params.get("status", "all")
    async with db.session_factory() as session:
        base = select(Idea, User).join(User, User.id == Idea.user_id)
        if q: base = base.where(or_(Idea.title.ilike(f"%{q}%"),Idea.problem.ilike(f"%{q}%"),Idea.description.ilike(f"%{q}%"),User.full_name.ilike(f"%{q}%")))
        if selected != "all" and selected in IDEA_STATUSES: base = base.where(Idea.status == selected)
        if type: base = base.where(Idea.category == type)
        cutoff_map={"7d":7,"30d":30,"90d":90}
        if period in cutoff_map: base=base.where(Idea.created_at >= datetime.utcnow()-timedelta(days=cutoff_map[period]))
        rank = sql_case({st: idx for idx, st in enumerate(IDEA_STATUSES)}, value=Idea.status, else_=999)
        order_map={"newest":[Idea.created_at.desc()],"oldest":[Idea.created_at.asc()],"title":[Idea.title.asc()],"workflow":[rank.asc(),Idea.created_at.desc()]}
        rows=(await session.execute(base.order_by(*order_map.get(sort,order_map["workflow"])))).all()
        all_ideas=(await session.scalars(select(Idea))).all(); counts={key:0 for key in IDEA_STATUSES}
        for item in all_ideas: counts[item.status]=counts.get(item.status,0)+1
        categories=sorted({i.category for i in all_ideas if i.category})
        return templates.TemplateResponse(request=request,name="ideas.html",context=ctx(request,rows=rows,counts=counts,selected=selected,statuses=IDEA_STATUSES,q=q,period=period,type=type,sort=sort,categories=categories))


@router.get("/admin/ideas/{idea_id}", response_class=HTMLResponse)
async def idea_detail(request: Request, idea_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        idea = await session.get(Idea, idea_id)
        if not idea:
            return HTMLResponse("Ідею не знайдено", status_code=404)
        author = await session.get(User, idea.user_id)
        responsible = await session.get(User, idea.responsible_user_id) if idea.responsible_user_id else None
        team = (await session.scalars(
            select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name.asc())
        )).all()
        return templates.TemplateResponse(
            request=request,
            name="idea_detail.html",
            context=ctx(request, idea=idea, author=author, responsible=responsible, team=team, statuses=IDEA_STATUSES),
        )


@router.post("/admin/ideas/{idea_id}/status")
async def idea_status(request: Request, idea_id: int, status: str = Form(...)):
    if r := guard(request): return r
    notify_id=None; notify_text=""
    async with db.session_factory() as session:
        idea = await session.get(Idea, idea_id)
        if idea and status in IDEA_STATUSES:
            now = datetime.utcnow()
            idea.status = status
            if status == "approved":
                idea.approved_at = idea.approved_at or now
                notify_id, notify_text = await _award_idea_approval_xp(session, idea)
            if status == "in_progress" and not idea.implementation_started_at:
                idea.implementation_started_at = now
            if status == "implemented":
                idea.progress_percent = 100
                idea.implemented_at = idea.implemented_at or now
            idea.updated_at = now
            await log_audit(session, "web_idea_status", actor_label=request.session.get("admin_name", "web"), entity_type="idea", entity_id=idea.id, details=f"{idea.title}: {idea_status_label(status)}")
            await session.commit()
    if notify_id and notify_text:
        await notify_telegram(notify_id, notify_text)
    referer = request.headers.get("referer") or "/admin/ideas"
    return RedirectResponse(referer, 303)


@router.post("/admin/ideas/{idea_id}/update")
async def idea_update(
    request: Request,
    idea_id: int,
    status: str = Form(...),
    category: str = Form("other"),
    problem: str = Form(""),
    description: str = Form(""),
    audience: str = Form(""),
    expected_result: str = Form(""),
    resources: str = Form(""),
    responsible_user_id: str = Form(""),
    admin_note: str = Form(""),
    project_team: str = Form(""),
    implementation_deadline: str = Form(""),
    budget_resources: str = Form(""),
    project_tasks: str = Form(""),
    progress_percent: int = Form(0),
    implementation_result: str = Form(""),
    remove_result_image: str | None = Form(None),
    result_photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    notify_id=None; notify_text=""
    assigned_notify_tg: int | None = None
    assigned_notify_text = ""
    async with db.session_factory() as session:
        idea = await session.get(Idea, idea_id)
        if not idea:
            return HTMLResponse("Ідею не знайдено", status_code=404)
        old_status = idea.status
        old_responsible_id = idea.responsible_user_id
        now = datetime.utcnow()
        if status in IDEA_STATUSES:
            idea.status = status
        idea.category = category or "other"
        idea.problem = problem.strip()
        idea.description = description.strip()
        idea.audience = audience.strip()
        idea.expected_result = expected_result.strip()
        idea.resources = resources.strip()
        idea.responsible_user_id = opt_int(responsible_user_id)
        idea.admin_note = admin_note.strip()
        if idea.responsible_user_id and idea.responsible_user_id != old_responsible_id:
            responsible_user = await session.get(User, idea.responsible_user_id)
            if responsible_user and responsible_user.tg_id:
                assigned_notify_tg = responsible_user.tg_id
                assigned_notify_text = (
                    f"💡 <b>Вас призначено відповідальним за ідею</b>\n\n"
                    f"<b>{html_escape(idea.title)}</b>\n"
                    f"Статус: <b>{html_escape(idea_status_label(idea.status))}</b>\n\n"
                    "Відкрийте деталі, щоб переглянути опис, завдання та прогрес."
                )

        # Mini-project block becomes meaningful after approval but may be prepared earlier.
        idea.project_team = project_team.strip()
        raw_deadline = implementation_deadline.strip()
        if raw_deadline:
            try:
                idea.implementation_deadline = datetime.fromisoformat(raw_deadline)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Некоректний дедлайн реалізації ідеї") from exc
        else:
            idea.implementation_deadline = None
        idea.budget_resources = budget_resources.strip()
        idea.project_tasks = project_tasks.strip()
        idea.progress_percent = max(0, min(100, int(progress_percent or 0)))
        idea.implementation_result = implementation_result.strip()

        if remove_result_image and idea.result_image_path:
            await delete_image(idea.result_image_path)
            idea.result_image_path = None
        new_img = await save_image(result_photo, "ideas")
        if new_img:
            if idea.result_image_path:
                await delete_image(idea.result_image_path)
            idea.result_image_path = new_img

        if idea.status == "approved":
            if not idea.approved_at:
                idea.approved_at = now
            notify_id, notify_text = await _award_idea_approval_xp(session, idea)
        if idea.status == "in_progress" and not idea.implementation_started_at:
            idea.implementation_started_at = now
        if idea.status == "implemented":
            idea.progress_percent = 100
            if not idea.implemented_at:
                idea.implemented_at = now
        elif old_status == "implemented" and idea.status != "implemented":
            idea.implemented_at = None

        idea.updated_at = now
        await log_audit(
            session, "web_idea_project_update", actor_label=request.session.get("admin_name", "web"),
            entity_type="idea", entity_id=idea.id,
            details=f"Оновлено картку/міні-проєкт «{idea.title}»: {idea_status_label(idea.status)}, прогрес {idea.progress_percent}%"
        )
        await session.commit()
    if notify_id and notify_text:
        await notify_telegram(notify_id, notify_text)
    if assigned_notify_tg and assigned_notify_text:
        await notify_telegram(
            assigned_notify_tg, assigned_notify_text,
            button_text="👁 Детально", callback_data=f"assigned_idea:{idea_id}",
        )
    return RedirectResponse(f"/admin/ideas/{idea_id}", 303)


@router.post("/admin/ideas/{idea_id}/delete")
async def idea_delete(request: Request, idea_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        idea = await session.get(Idea, idea_id)
        if not idea:
            return RedirectResponse("/admin/ideas",303)
        title = idea.title
        author_id = idea.user_id
        result_image = idea.result_image_path
        await session.delete(idea)
        await log_audit(session, "web_idea_delete", actor_label=request.session.get("admin_name","web"), entity_type="idea", entity_id=idea_id, details=f"Видалено ідею «{title}», автор ID {author_id}")
        await session.commit()
    if result_image:
        await delete_image(result_image)
    return RedirectResponse("/admin/ideas",303)

