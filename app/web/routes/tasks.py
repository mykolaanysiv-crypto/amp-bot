from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/tasks", response_class=HTMLResponse)
async def tasks(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "newest"):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        stmt = select(VolunteerTask)
        if q: stmt = stmt.where(or_(VolunteerTask.title.ilike(f"%{q}%"), VolunteerTask.description.ilike(f"%{q}%")))
        if status: stmt = stmt.where(VolunteerTask.status == status)
        if type == "solo": stmt = stmt.where(VolunteerTask.max_participants == 1)
        elif type == "team": stmt = stmt.where(VolunteerTask.max_participants > 1)
        cutoff_map={"7d":7,"30d":30,"90d":90}
        if period in cutoff_map: stmt = stmt.where(VolunteerTask.created_at >= datetime.utcnow()-timedelta(days=cutoff_map[period]))
        order_map={"oldest":VolunteerTask.created_at.asc(),"title":VolunteerTask.title.asc(),"deadline":VolunteerTask.deadline.asc().nullslast(),"newest":VolunteerTask.created_at.desc()}
        rows = (await session.scalars(stmt.order_by(order_map.get(sort, VolunteerTask.created_at.desc())))).all()
        participant_counts = {}; submitted_counts = {}; approved_counts = {}
        for task in rows:
            participant_counts[task.id] = int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.task_id == task.id, VolunteerTaskParticipation.status != "cancelled")) or 0)
            submitted_counts[task.id] = int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.task_id == task.id, VolunteerTaskParticipation.status == "submitted")) or 0)
            approved_counts[task.id] = int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.task_id == task.id, VolunteerTaskParticipation.status == "approved")) or 0)
        return templates.TemplateResponse(request=request,name="tasks.html",context=ctx(request,rows=rows,participant_counts=participant_counts,submitted_counts=submitted_counts,approved_counts=approved_counts,today=date.today(),q=q,status=status,period=period,type=type,sort=sort))


@router.get("/admin/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail_web(request: Request, task_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        task = await session.get(VolunteerTask, task_id)
        if not task:
            return HTMLResponse("Волонтерську задачу не знайдено", status_code=404)
        participants = (await session.execute(
            select(VolunteerTaskParticipation, User)
            .join(User, User.id == VolunteerTaskParticipation.user_id)
            .where(VolunteerTaskParticipation.task_id == task.id)
            .order_by(VolunteerTaskParticipation.joined_at.asc())
        )).all()
        active_count = sum(1 for part, _user in participants if part.status != "cancelled")
        return templates.TemplateResponse(
            request=request, name="task_detail.html",
            context=ctx(request, task=task, participants=participants, active_count=active_count, today=date.today()),
        )


@router.post("/admin/tasks/create")
async def task_create(
    request: Request,
    title: str = Form(...), description: str = Form(""), xp_reward: int = Form(20),
    hours_reward: float = Form(0), max_participants: int = Form(1),
    deadline_day: str = Form(""), deadline_month: str = Form(""), deadline_year: str = Form(""), deadline_time: str = Form(""),
    status: str = Form("open"), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    deadline = compose_optional_datetime_fields(deadline_day, deadline_month, deadline_year, deadline_time, entity_label="дедлайну волонтерської задачі")
    img = await save_image(photo, "tasks")
    campaign_id=None
    async with db.session_factory() as session:
        xp_reward = normalize_task_xp(xp_reward, hours_reward)
        task = VolunteerTask(
            title=title.strip(), description=description.strip(), xp_reward=xp_reward,
            hours_reward=max(0, hours_reward), deadline=deadline,
            max_participants=max(1, max_participants), status=status if status in {"draft", "open", "closed"} else "open",
            image_path=img,
        )
        session.add(task)
        await session.flush()
        await log_audit(session, "web_task_create", actor_label=request.session.get("admin_name", "web"), entity_type="task", entity_id=task.id, details=task.title)
        if task.status=="open":
            users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
            campaign_id=await _queue_system_broadcast(session,users,f"✅ <b>Нова волонтерська задача</b>\n\n<b>{task.title}</b>\n⚡ {task.xp_reward} XP · ⏱ {task.hours_reward:g} год\n\nВідкрий «✅ Волонтерство» у боті, щоб долучитися.",author_label=request.session.get("admin_name","web"),audience_label=f"Нова задача: {task.title}",template_code="task_created")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/tasks", 303)


@router.post("/admin/tasks/{task_id}/update")
async def task_update(
    request: Request, task_id: int,
    title: str = Form(...), description: str = Form(""), xp_reward: int = Form(20),
    hours_reward: float = Form(0), max_participants: int = Form(1),
    deadline_day: str = Form(""), deadline_month: str = Form(""), deadline_year: str = Form(""), deadline_time: str = Form(""),
    status: str = Form("open"), remove_image: str | None = Form(None), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    deadline = compose_optional_datetime_fields(deadline_day, deadline_month, deadline_year, deadline_time, entity_label="дедлайну волонтерської задачі")
    campaign_id=None
    async with db.session_factory() as session:
        task = await session.get(VolunteerTask, task_id)
        if not task:
            return HTMLResponse("Волонтерську задачу не знайдено", status_code=404)
        was_public=task.status in {"open","postponed"}
        active_count = int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(
            VolunteerTaskParticipation.task_id == task.id,
            VolunteerTaskParticipation.status != "cancelled",
        )) or 0)
        task.title = title.strip()
        task.description = description.strip()
        task.hours_reward = max(0, hours_reward)
        task.xp_reward = normalize_task_xp(xp_reward, task.hours_reward)
        task.deadline = deadline
        task.max_participants = max(active_count, max(1, max_participants))
        if not task.cancelled_at and task.status not in {"postponed", "completed"} and status in {"open", "closed"}:
            task.status = status
        if remove_image:
            await delete_image(task.image_path)
            task.image_path = None
        img = await save_image(photo, "tasks")
        if img:
            await delete_image(task.image_path)
            task.image_path = img
        await log_audit(session, "web_task_update", actor_label=request.session.get("admin_name", "web"), entity_type="task", entity_id=task.id, details=task.title)
        if not was_public and task.status=="open":
            users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
            campaign_id=await _queue_system_broadcast(session,users,f"✅ <b>Нова волонтерська задача</b>\n\n<b>{task.title}</b>\n⚡ {task.xp_reward} XP · ⏱ {task.hours_reward:g} год\n\nВідкрий «✅ Волонтерство» у боті, щоб долучитися.",author_label=request.session.get("admin_name","web"),audience_label=f"Нова задача: {task.title}",template_code="task_published")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse(request.headers.get("referer") or f"/admin/tasks/{task_id}", 303)


@router.post("/admin/tasks/{task_id}/participant/{part_id}/{action}")
async def task_participant_action(request: Request, task_id: int, part_id: int, action: str, admin_note: str = Form("")):
    if r := guard(request): return r
    notify_id = None
    notify_text = ""
    async with db.session_factory() as session:
        task = await session.get(VolunteerTask, task_id)
        part = await session.get(VolunteerTaskParticipation, part_id)
        if not task or not part or part.task_id != task.id:
            return HTMLResponse("Участь у задачі не знайдено", status_code=404)
        if task.cancelled_at or task.status == "cancelled":
            return RedirectResponse(f"/admin/tasks/{task_id}", 303)
        user = await session.get(User, part.user_id)
        note = admin_note.strip()
        if action == "approve" and part.status == "submitted" and user:
            result = await approve_volunteer_task_participation(session, task, part, user, admin_note=note)
            if not result:
                return RedirectResponse(f"/admin/tasks/{task_id}", 303)
            total, level, leveled = result
            notify_id = user.tg_id
            notify_text = f"✅ Задачу <b>{task.title}</b> підтверджено.\n⚡ +{task.xp_reward} XP • ⏱ +{task.hours_reward:g} год.\nЗагальний досвід: <b>{total} XP</b>" + (f"\n🎉 Новий рівень: <b>{level}</b>" if leveled else "")
        elif action == "return" and part.status == "submitted":
            part.status = "returned"
            part.admin_note = note
            if user:
                notify_id = user.tg_id
                notify_text = f"↩ Задачу <b>{task.title}</b> повернуто на доопрацювання." + (f"\n💬 {note}" if note else "")
        elif action == "remove" and part.status != "approved":
            part.status = "cancelled"
            part.admin_note = note
            if user:
                notify_id = user.tg_id
                notify_text = f"ℹ️ Вашу участь у задачі <b>{task.title}</b> скасовано адміністратором." + (f"\n💬 {note}" if note else "")
        else:
            return RedirectResponse(f"/admin/tasks/{task_id}",303)
        await log_audit(session, f"web_task_participant_{action}", actor_label=request.session.get("admin_name","web"), entity_type="volunteer_task_participation", entity_id=part.id, details=f"{task.title}; {user.full_name if user else ''}")
        await session.commit()
    if notify_id:
        await notify_telegram(notify_id, notify_text)
    return RedirectResponse(f"/admin/tasks/{task_id}",303)


@router.post("/admin/tasks/{task_id}/postpone")
async def task_postpone(request: Request, task_id: int, reason: str = Form(...), deadline_day: str = Form(...), deadline_month: str = Form(...), deadline_year: str = Form(...), deadline_time: str = Form(...)):
    if r := guard(request): return r
    reason=reason.strip()
    if not reason: raise HTTPException(status_code=400,detail="Вкажіть причину перенесення волонтерської задачі.")
    new_at=compose_optional_datetime_fields(deadline_day,deadline_month,deadline_year,deadline_time,entity_label="нового дедлайну волонтерської задачі")
    if not new_at or new_at<=datetime.utcnow(): raise HTTPException(status_code=400,detail="Новий дедлайн має бути в майбутньому.")
    campaign_id=None
    async with db.session_factory() as session:
        task=await session.get(VolunteerTask,task_id)
        if not task: raise HTTPException(status_code=404,detail="Волонтерську задачу не знайдено.")
        if task.cancelled_at or task.status=="cancelled": raise HTTPException(status_code=409,detail="Скасовану задачу не можна переносити.")
        users=list((await session.scalars(select(User).join(VolunteerTaskParticipation,VolunteerTaskParticipation.user_id==User.id).where(VolunteerTaskParticipation.task_id==task.id,VolunteerTaskParticipation.status!="cancelled").distinct())).all())
        task.deadline=new_at; task.status="postponed"; task.postponed_reason=reason; task.postponed_at=datetime.utcnow()
        campaign_id=await _queue_system_broadcast(session,users,_postponed_notice_text("Волонтерську задачу",task.title,new_at,reason),author_label=request.session.get("admin_name","web"),audience_label=f"Учасники перенесеної задачі: {task.title}",template_code="task_postponed")
        await log_audit(session,"web_task_postpone",actor_label=request.session.get("admin_name","web"),entity_type="task",entity_id=task.id,details=f"Новий дедлайн {new_at}; причина: {reason}; повідомлень: {len(users)}")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/tasks/{task_id}",303)


@router.post("/admin/tasks/{task_id}/cancel")
async def task_cancel(request: Request, task_id: int, reason: str = Form(...)):
    if r := guard(request): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину скасування волонтерської задачі.")
    campaign_id: int | None = None
    async with db.session_factory() as session:
        task = await session.get(VolunteerTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Волонтерську задачу не знайдено.")
        if task.cancelled_at or task.status == "cancelled":
            raise HTTPException(status_code=409, detail="Задачу вже скасовано.")
        if task.status == "completed":
            raise HTTPException(status_code=409, detail="Завершену задачу не можна скасувати.")
        users = list((await session.scalars(
            select(User)
            .join(VolunteerTaskParticipation, VolunteerTaskParticipation.user_id == User.id)
            .where(VolunteerTaskParticipation.task_id == task.id, VolunteerTaskParticipation.status != "cancelled")
            .distinct()
        )).all())
        task.status = "cancelled"
        task.cancellation_reason = reason
        task.cancelled_at = datetime.utcnow()
        campaign_id = await _queue_system_broadcast(
            session, users, _entity_notice_text("Волонтерську задачу", task.title, reason),
            author_label=request.session.get("admin_name", "web"),
            audience_label=f"Учасники скасованої волонтерської задачі: {task.title}",
            template_code="task_cancelled",
        )
        await log_audit(
            session, "web_task_cancel", actor_label=request.session.get("admin_name", "web"),
            entity_type="task", entity_id=task.id,
            details=f"Скасовано волонтерську задачу «{task.title}». Причина: {reason}. Повідомлень у черзі: {len(users)}.",
        )
        await session.commit()
    if campaign_id:
        _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/tasks/{task_id}", status_code=303)


@router.post("/admin/tasks/{task_id}/delete")
async def task_delete(request: Request, task_id: int, reason: str = Form(...)):
    if r := guard_permission(request, "volunteer.manage"): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину видалення волонтерської задачі.")
    campaign_id: int | None = None
    image_path: str | None = None
    async with db.session_factory() as session:
        task = await session.get(VolunteerTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Волонтерську задачу не знайдено.")
        users = list((await session.scalars(
            select(User)
            .join(VolunteerTaskParticipation, VolunteerTaskParticipation.user_id == User.id)
            .where(VolunteerTaskParticipation.task_id == task.id, VolunteerTaskParticipation.status != "cancelled")
            .distinct()
        )).all())
        title = task.title
        image_path = task.image_path
        campaign_id = await _queue_system_broadcast(
            session, users, _entity_notice_text("Волонтерську задачу", title, reason, deleted=True),
            author_label=request.session.get("admin_name", "web"),
            audience_label=f"Учасники видаленої волонтерської задачі: {title}",
            template_code="task_deleted",
        )
        await session.execute(delete(VolunteerTaskParticipation).where(VolunteerTaskParticipation.task_id == task.id))
        await log_audit(
            session, "web_task_delete", actor_label=request.session.get("admin_name", "web"),
            entity_type="task", entity_id=task.id,
            details=f"Видалено волонтерську задачу «{title}». Причина: {reason}. Повідомлень у черзі: {len(users)}.",
        )
        await session.delete(task)
        await session.commit()
    if image_path:
        await delete_image(image_path)
    if campaign_id:
        _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/tasks", status_code=303)

