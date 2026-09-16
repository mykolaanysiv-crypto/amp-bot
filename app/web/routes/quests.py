from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.content_views import content_view_stat, content_view_stats
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/quests", response_class=HTMLResponse)
async def quests(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "newest", review: str = ""):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        stmt = select(Quest)
        if q: stmt = stmt.where(or_(Quest.title.ilike(f"%{q}%"), Quest.description.ilike(f"%{q}%")))
        if status: stmt = stmt.where(Quest.status == status)
        if type: stmt = stmt.where(Quest.quest_type == type)
        if review == "completed": stmt = stmt.where(Quest.id.in_(select(QuestParticipation.quest_id).where(QuestParticipation.status == "completed")))
        cutoff_map={"7d":7,"30d":30,"90d":90}
        if period in cutoff_map: stmt = stmt.where(Quest.starts_at >= clock.storage_utc()-timedelta(days=cutoff_map[period]))
        order_map={"oldest":Quest.starts_at.asc(),"title":Quest.title.asc(),"deadline":Quest.ends_at.asc().nullslast(),"newest":Quest.starts_at.desc()}
        rows = (await session.scalars(stmt.order_by(order_map.get(sort, Quest.starts_at.desc())).limit(250))).all()
        team = await seed_default_team(session)
        participant_counts = {}; completed_counts = {}
        for row in rows:
            participant_counts[row.id] = int(await session.scalar(select(func.count(QuestParticipation.id)).where(QuestParticipation.quest_id == row.id)) or 0)
            completed_counts[row.id] = int(await session.scalar(select(func.count(QuestParticipation.id)).where(QuestParticipation.quest_id == row.id, QuestParticipation.status == "approved")) or 0)
        view_stats = await content_view_stats(session, "quest", [row.id for row in rows])
        return templates.TemplateResponse(request=request,name="quests.html",context=ctx(request,rows=rows,team=team,participant_counts=participant_counts,completed_counts=completed_counts,view_stats=view_stats,today=clock.today_local(),q=q,status=status,period=period,type=type,sort=sort,review=review))


@router.get("/admin/quests/{quest_id}", response_class=HTMLResponse)
async def quest_detail_web(request: Request, quest_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        q = await session.get(Quest, quest_id)
        if not q:
            return HTMLResponse("Квест не знайдено", status_code=404)
        participants = (await session.execute(
            select(QuestParticipation, User)
            .join(User, User.id == QuestParticipation.user_id)
            .where(QuestParticipation.quest_id == q.id)
            .order_by(QuestParticipation.joined_at.asc())
        )).all()
        view_stat = await content_view_stat(session, "quest", q.id)
        return templates.TemplateResponse(
            request=request, name="quest_detail.html",
            context=ctx(request, q=q, participants=participants, view_stat=view_stat, today=clock.today_local()),
        )


@router.post("/admin/quests/{quest_id}/participant/{part_id}/{action}")
async def quest_participant_action(request: Request, quest_id: int, part_id: int, action: str):
    if r := guard(request): return r
    notify_id = None
    notify_text = ""
    async with db.session_factory() as session:
        q = await session.get(Quest, quest_id)
        part = await session.get(QuestParticipation, part_id)
        if not q or not part or part.quest_id != q.id:
            return HTMLResponse("Участь у квесті не знайдено", status_code=404)
        if q.cancelled_at:
            return RedirectResponse(f"/admin/quests/{quest_id}", 303)
        user = await session.get(User, part.user_id)
        if action == "approve" and part.status == "completed" and user:
            result = await approve_quest_participation(session, q, part, user)
            if not result:
                return RedirectResponse(f"/admin/quests/{quest_id}", 303)
            total, level, leveled = result
            notify_id = user.tg_id
            notify_text = f"🏆 Квест <b>{q.title}</b> підтверджено!\n⚡ +{q.xp_reward} XP\nЗагальний досвід: <b>{total} XP</b>" + (f"\n🎉 Новий рівень: <b>{level}</b>" if leveled else "")
        elif action == "return" and part.status == "completed":
            part.status = "joined"
            part.completed_at = None
            if user:
                notify_id = user.tg_id
                notify_text = f"↩ Виконання квесту <b>{q.title}</b> повернуто. Уточніть результат і подайте його повторно."
        elif action == "remove" and part.status != "approved":
            part.status = "cancelled"
            part.completed_at = None
            if user:
                notify_id = user.tg_id
                notify_text = f"ℹ️ Вашу участь у квесті <b>{q.title}</b> скасовано адміністратором."
        else:
            return RedirectResponse(f"/admin/quests/{quest_id}", 303)
        await log_audit(session, f"web_quest_participant_{action}", actor_label=request.session.get("admin_name","web"), entity_type="quest_participation", entity_id=part.id, details=f"{q.title}; {user.full_name if user else ''}")
        await session.commit()
    if notify_id:
        await notify_telegram(notify_id, notify_text)
    return RedirectResponse(f"/admin/quests/{quest_id}", 303)


@router.post("/admin/quests/create")
async def quest_create(
    request: Request, title: str = Form(...), description: str = Form(""), xp_reward: int = Form(20),
    quest_type: str = Form("individual"), target_value: int = Form(1),
    deadline_day: str = Form(""), deadline_month: str = Form(""), deadline_year: str = Form(""), deadline_time: str = Form(""),
    active: str | None = Form(None), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    ends_at = compose_optional_datetime_fields(deadline_day, deadline_month, deadline_year, deadline_time, entity_label="дедлайну квесту")
    img = await save_image(photo, "quests")
    campaign_id=None
    async with db.session_factory() as session:
        team = await seed_default_team(session)
        quest_type = "team" if quest_type == "team" else "individual"
        xp_reward = normalize_quest_xp(xp_reward, quest_type)
        q = Quest(
            title=title.strip(), description=description.strip(), xp_reward=xp_reward, quest_type=quest_type,
            team_id=team.id if quest_type == "team" else None, target_value=max(1, target_value), progress_value=0,
            active=bool(active), status="open" if bool(active) else "closed", ends_at=ends_at, image_path=img,
        )
        session.add(q)
        await session.flush()
        await log_audit(session, "web_quest_create", actor_label=request.session.get("admin_name", "web"), entity_type="quest", entity_id=q.id, details=q.title)
        if q.active:
            users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
            campaign_id=await _queue_system_broadcast(session,users,f"🎯 <b>Новий квест</b>\n\n<b>{q.title}</b>\n⚡ {q.xp_reward} XP\n\nВідкрий «🎯 Квести» у боті, щоб долучитися.",author_label=request.session.get("admin_name","web"),audience_label=f"Новий квест: {q.title}",template_code="quest_created")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/quests", 303)


@router.post("/admin/quests/{quest_id}/update")
async def quest_update(
    request: Request, quest_id: int, title: str = Form(...), description: str = Form(""), xp_reward: int = Form(20),
    quest_type: str = Form("individual"), target_value: int = Form(1),
    deadline_day: str = Form(""), deadline_month: str = Form(""), deadline_year: str = Form(""), deadline_time: str = Form(""),
    active: str | None = Form(None), remove_image: str | None = Form(None), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    ends_at = compose_optional_datetime_fields(deadline_day, deadline_month, deadline_year, deadline_time, entity_label="дедлайну квесту")
    campaign_id=None
    async with db.session_factory() as session:
        q = await session.get(Quest, quest_id)
        team = await seed_default_team(session)
        if q:
            was_public=bool(q.active) and q.status in {"open","postponed"}
            q.title = title.strip()
            q.description = description.strip()
            q.quest_type = "team" if quest_type == "team" else "individual"
            q.xp_reward = normalize_quest_xp(xp_reward, q.quest_type)
            q.team_id = team.id if q.quest_type == "team" else None
            q.target_value = max(1, target_value)
            q.ends_at = ends_at
            now_utc = clock.now_utc()
            if q.cancelled_at:
                q.active = False
            elif q.ends_at and clock.local_wall_to_utc(q.ends_at) < now_utc:
                q.active = False
                q.status = "completed"
            else:
                q.active = bool(active)
                if q.status != "postponed":
                    q.status = "open" if q.active else "closed"
            if remove_image:
                await delete_image(q.image_path)
                q.image_path = None
            img = await save_image(photo, "quests")
            if img:
                await delete_image(q.image_path)
                q.image_path = img
            await log_audit(session, "web_quest_update", actor_label=request.session.get("admin_name", "web"), entity_type="quest", entity_id=q.id, details=q.title)
            if not was_public and q.active and q.status=="open":
                users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
                campaign_id=await _queue_system_broadcast(session,users,f"🎯 <b>Новий квест</b>\n\n<b>{q.title}</b>\n⚡ {q.xp_reward} XP\n\nВідкрий «🎯 Квести» у боті, щоб долучитися.",author_label=request.session.get("admin_name","web"),audience_label=f"Новий квест: {q.title}",template_code="quest_published")
            await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse(request.headers.get("referer") or f"/admin/quests/{quest_id}", 303)


@router.post("/admin/quests/{quest_id}/progress")
async def quest_progress(request:Request,quest_id:int,delta:int=Form(...)):
    if r := guard(request): return r
    async with db.session_factory() as session:
        q=await session.get(Quest,quest_id)
        if q:
            await _refresh_lifecycle(session)
            await session.refresh(q)
        if q and not q.cancelled_at and q.status != "completed" and q.quest_type=="team" and not q.completed:
            q.progress_value=max(0,q.progress_value+delta); count=await complete_team_quest(session,q); await log_audit(session,"web_team_quest_progress",actor_label=request.session.get("admin_name","web"),entity_type="quest",entity_id=q.id,details=f"delta={delta}; awarded={count}"); await session.commit()
    return RedirectResponse(request.headers.get("referer") or f"/admin/quests/{quest_id}",303)


@router.post("/admin/quests/{quest_id}/postpone")
async def quest_postpone(request: Request, quest_id: int, reason: str = Form(...), deadline_day: str = Form(...), deadline_month: str = Form(...), deadline_year: str = Form(...), deadline_time: str = Form(...)):
    if r := guard(request): return r
    reason = reason.strip()
    if not reason: raise HTTPException(status_code=400, detail="Вкажіть причину перенесення квесту.")
    new_at = compose_optional_datetime_fields(deadline_day, deadline_month, deadline_year, deadline_time, entity_label="нового дедлайну квесту")
    if not new_at or new_at <= clock.storage_utc(): raise HTTPException(status_code=400, detail="Новий дедлайн має бути в майбутньому.")
    campaign_id=None
    async with db.session_factory() as session:
        quest=await session.get(Quest,quest_id)
        if not quest: raise HTTPException(status_code=404,detail="Квест не знайдено.")
        await _refresh_lifecycle(session)
        await session.refresh(quest)
        if quest.cancelled_at or quest.status=="cancelled": raise HTTPException(status_code=409,detail="Скасований квест не можна переносити.")
        if quest.status == "completed": raise HTTPException(status_code=409, detail="Завершений квест не можна переносити. Вкажіть новий дедлайн через редагування лише до завершення.")
        users=list((await session.scalars(select(User).join(QuestParticipation,QuestParticipation.user_id==User.id).where(QuestParticipation.quest_id==quest.id,QuestParticipation.status!="cancelled").distinct())).all())
        quest.ends_at=new_at; quest.active=True; quest.status="postponed"; quest.postponed_reason=reason; quest.postponed_at=clock.storage_utc(); quest.completed=False
        campaign_id=await _queue_system_broadcast(session,users,_postponed_notice_text("Квест",quest.title,new_at,reason),author_label=request.session.get("admin_name","web"),audience_label=f"Учасники перенесеного квесту: {quest.title}",template_code="quest_postponed")
        await log_audit(session,"web_quest_postpone",actor_label=request.session.get("admin_name","web"),entity_type="quest",entity_id=quest.id,details=f"Новий дедлайн {new_at}; причина: {reason}; повідомлень: {len(users)}")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/quests/{quest_id}",303)


@router.post("/admin/quests/{quest_id}/cancel")
async def quest_cancel(request: Request, quest_id: int, reason: str = Form(...)):
    if r := guard(request): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину скасування квесту.")
    campaign_id: int | None = None
    async with db.session_factory() as session:
        quest = await session.get(Quest, quest_id)
        if not quest:
            raise HTTPException(status_code=404, detail="Квест не знайдено.")
        if quest.cancelled_at or quest.status == "cancelled":
            raise HTTPException(status_code=409, detail="Квест уже скасовано.")
        if quest.status == "completed":
            raise HTTPException(status_code=409, detail="Завершений квест не можна скасувати.")
        users = list((await session.scalars(
            select(User)
            .join(QuestParticipation, QuestParticipation.user_id == User.id)
            .where(QuestParticipation.quest_id == quest.id, QuestParticipation.status != "cancelled")
            .distinct()
        )).all())
        quest.active = False
        quest.status = "cancelled"
        quest.cancellation_reason = reason
        quest.cancelled_at = clock.storage_utc()
        campaign_id = await _queue_system_broadcast(
            session, users, _entity_notice_text("Квест", quest.title, reason),
            author_label=request.session.get("admin_name", "web"),
            audience_label=f"Учасники скасованого квесту: {quest.title}",
            template_code="quest_cancelled",
        )
        await log_audit(
            session, "web_quest_cancel", actor_label=request.session.get("admin_name", "web"),
            entity_type="quest", entity_id=quest.id,
            details=f"Скасовано квест «{quest.title}». Причина: {reason}. Повідомлень у черзі: {len(users)}.",
        )
        await session.commit()
    if campaign_id:
        _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/quests/{quest_id}", status_code=303)


@router.post("/admin/quests/{quest_id}/delete")
async def quest_delete(request: Request, quest_id: int, reason: str = Form(...)):
    if r := guard_permission(request, "quests.manage"): return r
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Вкажіть причину видалення квесту.")
    campaign_id: int | None = None
    image_path: str | None = None
    async with db.session_factory() as session:
        quest = await session.get(Quest, quest_id)
        if not quest:
            raise HTTPException(status_code=404, detail="Квест не знайдено.")
        users = list((await session.scalars(
            select(User)
            .join(QuestParticipation, QuestParticipation.user_id == User.id)
            .where(QuestParticipation.quest_id == quest.id, QuestParticipation.status != "cancelled")
            .distinct()
        )).all())
        title = quest.title
        image_path = quest.image_path
        campaign_id = await _queue_system_broadcast(
            session, users, _entity_notice_text("Квест", title, reason, deleted=True),
            author_label=request.session.get("admin_name", "web"),
            audience_label=f"Учасники видаленого квесту: {title}",
            template_code="quest_deleted",
        )
        await session.execute(delete(TeamQuestContribution).where(TeamQuestContribution.quest_id == quest.id))
        await session.execute(delete(QuestParticipation).where(QuestParticipation.quest_id == quest.id))
        await log_audit(
            session, "web_quest_delete", actor_label=request.session.get("admin_name", "web"),
            entity_type="quest", entity_id=quest.id,
            details=f"Видалено квест «{title}». Причина: {reason}. Повідомлень у черзі: {len(users)}.",
        )
        await session.delete(quest)
        await session.commit()
    if image_path:
        await delete_image(image_path)
    if campaign_id:
        _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/quests", status_code=303)

