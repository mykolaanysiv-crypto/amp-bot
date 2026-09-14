from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/activities", response_class=HTMLResponse)
async def activities_page(request: Request, status: str = "attention", q: str = "", period: str = "", type: str = "", sort: str = "newest"):
    if r := guard(request): return r
    async with db.session_factory() as session:
        catalog_stmt = select(ActivityType)
        if q: catalog_stmt = catalog_stmt.where(or_(ActivityType.title.ilike(f"%{q}%"), ActivityType.description.ilike(f"%{q}%")))
        if type:
            if type.isdigit(): catalog_stmt = catalog_stmt.where(ActivityType.id == int(type))
            else: catalog_stmt = catalog_stmt.where(ActivityType.category == type)
        catalog = (await session.scalars(catalog_stmt.order_by(ActivityType.active.desc(), ActivityType.sort_order, ActivityType.title))).all()
        stmt = select(ActivityApplication, ActivityType, User).join(ActivityType, ActivityType.id == ActivityApplication.activity_type_id).join(User, User.id == ActivityApplication.user_id)
        if q: stmt = stmt.where(or_(ActivityType.title.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"), ActivityApplication.result_note.ilike(f"%{q}%")))
        if type:
            if type.isdigit(): stmt = stmt.where(ActivityType.id == int(type))
            else: stmt = stmt.where(ActivityType.category == type)
        if status == "attention": stmt = stmt.where(ActivityApplication.status.in_(["activity_requested", "activity_submitted"]))
        elif status in ACTIVITY_APPLICATION_STATUSES: stmt = stmt.where(ActivityApplication.status == status)
        cutoff_map={"7d":7,"30d":30,"90d":90}
        if period in cutoff_map: stmt = stmt.where(ActivityApplication.requested_at >= datetime.utcnow()-timedelta(days=cutoff_map[period]))
        order_map={"oldest":ActivityApplication.requested_at.asc(),"name":User.full_name.asc(),"newest":ActivityApplication.requested_at.desc()}
        rows = (await session.execute(stmt.order_by(order_map.get(sort, ActivityApplication.requested_at.desc())).limit(400))).all()
        counts = {st: int(await session.scalar(select(func.count(ActivityApplication.id)).where(ActivityApplication.status == st)) or 0) for st in ACTIVITY_APPLICATION_STATUSES}
        categories = sorted({a.category for a in (await session.scalars(select(ActivityType))).all() if a.category})
        return templates.TemplateResponse(request=request,name="activities.html",context=ctx(request,catalog=catalog,rows=rows,counts=counts,selected=status,statuses=ACTIVITY_APPLICATION_STATUSES,automatic_guide=AUTOMATIC_XP_GUIDE,q=q,period=period,type=type,sort=sort,categories=categories))


@router.post("/admin/activities/create")
async def activity_create(
    request: Request, title: str = Form(...), category: str = Form("other"),
    description: str = Form(""), instructions: str = Form(""),
    xp_reward: int = Form(10), hours_reward: float = Form(0),
):
    if r := guard(request): return r
    title = title.strip()
    if not title:
        return RedirectResponse("/admin/activities", 303)
    code = f"custom_{uuid4().hex[:12]}"
    xp_reward = max(1, min(40, int(xp_reward)))
    hours_reward = max(0.0, min(12.0, float(hours_reward)))
    campaign_id=None
    async with db.session_factory() as session:
        row = ActivityType(
            code=code, title=title, category=category or "other", description=description.strip(),
            instructions=instructions.strip(), xp_reward=xp_reward, hours_reward=hours_reward,
            active=True, sort_order=500,
        )
        session.add(row); await session.flush()
        await log_audit(session, "web_activity_create", actor_label=request.session.get("admin_name", "web"), entity_type="activity_type", entity_id=row.id, details=f"{row.title}: {row.xp_reward} XP")
        users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
        campaign_id=await _queue_system_broadcast(session,users,f"⚡ <b>Нова активність</b>\n\n<b>{row.title}</b>\n🎁 {row.xp_reward} XP\n\nВідкрий «⚡ Активності» у боті, щоб переглянути умови.",author_label=request.session.get("admin_name","web"),audience_label=f"Нова активність: {row.title}",template_code="activity_created")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/activities", 303)


@router.post("/admin/activities/{activity_id}/update")
async def activity_update(
    request: Request, activity_id: int, title: str = Form(...), category: str = Form("other"),
    description: str = Form(""), instructions: str = Form(""), xp_reward: int = Form(10),
    hours_reward: float = Form(0), active: str | None = Form(None),
):
    if r := guard(request): return r
    campaign_id=None
    async with db.session_factory() as session:
        row = await session.get(ActivityType, activity_id)
        if row:
            was_public=bool(row.active)
            row.title = title.strip() or row.title
            row.category = category or "other"
            row.description = description.strip(); row.instructions = instructions.strip()
            row.xp_reward = max(1, min(40, int(xp_reward)))
            row.hours_reward = max(0.0, min(12.0, float(hours_reward)))
            row.active = active == "on"
            await log_audit(session, "web_activity_update", actor_label=request.session.get("admin_name", "web"), entity_type="activity_type", entity_id=row.id, details=f"{row.title}: {row.xp_reward} XP; active={row.active}")
            if not was_public and row.active:
                users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)))).all())
                campaign_id=await _queue_system_broadcast(session,users,f"⚡ <b>Нова активність</b>\n\n<b>{row.title}</b>\n🎁 {row.xp_reward} XP\n\nВідкрий «⚡ Активності» у боті, щоб переглянути умови.",author_label=request.session.get("admin_name","web"),audience_label=f"Нова активність: {row.title}",template_code="activity_published")
            await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse("/admin/activities", 303)


@router.post("/admin/activity-applications/{application_id}/{action}")
async def activity_application_action(request: Request, application_id: int, action: str, admin_note: str = Form("")):
    if r := guard(request): return r
    notify_id = None; notify_text = ""
    async with db.session_factory() as session:
        app_row = await session.get(ActivityApplication, application_id)
        if not app_row:
            return RedirectResponse("/admin/activities", 303)
        item = await session.get(ActivityType, app_row.activity_type_id)
        user = await session.get(User, app_row.user_id)
        app_row.admin_note = admin_note.strip() or app_row.admin_note
        actor_label = request.session.get("admin_name", "web")
        action_code = ""
        if action == "approve" and app_row.status == "activity_requested":
            app_row.status = "activity_approved"; app_row.approved_at = datetime.utcnow()
            action_code = "web_activity_approve"
            notify_text = f"✅ Заявку на активність <b>{item.title}</b> погоджено. Можна виконувати. Після завершення передайте результат через «⚡ Активності → Мої заявки»."
        elif action == "reject" and app_row.status == "activity_requested":
            app_row.status = "activity_rejected"
            action_code = "web_activity_reject"
            notify_text = f"❌ Заявку на активність <b>{item.title}</b> відхилено." + (f"\nКоментар: {app_row.admin_note}" if app_row.admin_note else "")
        elif action == "return" and app_row.status == "activity_submitted":
            app_row.status = "activity_approved"; app_row.submitted_at = None
            action_code = "web_activity_return"
            notify_text = f"↩ Результат активності <b>{item.title}</b> повернуто на уточнення/доопрацювання." + (f"\nКоментар: {app_row.admin_note}" if app_row.admin_note else "")
        elif action == "complete" and app_row.status in {"activity_approved", "activity_submitted"}:
            result = await complete_activity_application(session, app_row, None)
            if result:
                _, total, level, _ = result
                action_code = "web_activity_complete"
                notify_text = f"🏁 Активність <b>{item.title}</b> підтверджено!\n⚡ +{app_row.xp_reward} XP • ⏱ +{app_row.hours_reward:g} год.\nЗагальний досвід: <b>{total} XP</b>\nРівень: {level}"
        if action_code:
            await log_audit(session, action_code, actor_label=actor_label, entity_type="activity_application", entity_id=app_row.id, details=f"{item.title}; {user.full_name if user else ''}; {activity_status_label(app_row.status)}")
            await session.commit()
            notify_id = user.tg_id if user else None
    if notify_id and notify_text:
        await notify_telegram(notify_id, notify_text)
    return RedirectResponse("/admin/activities", 303)


@router.post("/admin/activity-applications/{application_id}/evidence")
async def activity_application_evidence(
    request: Request, application_id: int,
    remove_image: str | None = Form(None),
    photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    async with db.session_factory() as session:
        row = await session.get(ActivityApplication, application_id)
        if not row:
            raise HTTPException(status_code=404, detail="Заявку не знайдено")
        if remove_image and row.result_image_path:
            await delete_image(row.result_image_path)
            row.result_image_path = None
        img = await save_image(photo, "activity_results")
        if img:
            if row.result_image_path:
                await delete_image(row.result_image_path)
            row.result_image_path = img
        await log_audit(session, "web_activity_evidence", actor_label=request.session.get("admin_name","web"), entity_type="activity_application", entity_id=row.id, details="Оновлено фото/скріншот підтвердження")
        await session.commit()
    return RedirectResponse(request.headers.get("referer") or "/admin/activities", 303)

