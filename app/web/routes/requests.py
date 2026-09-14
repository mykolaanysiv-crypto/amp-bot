from __future__ import annotations

from fastapi import APIRouter
from app.ui_labels import REQUEST_CATEGORIES, REQUEST_PRIORITIES, REQUEST_STATUSES
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/requests", response_class=HTMLResponse)
async def requests_page(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "updated", overdue: str = ""):
    if r := guard(request): return r
    selected_status = status or request.query_params.get("status", "all")
    selected_category = type or request.query_params.get("category", "all")
    async with db.session_factory() as session:
        stmt = select(RequestCase, User).join(User, User.id == RequestCase.user_id)
        if q: stmt=stmt.where(or_(RequestCase.case_number.ilike(f"%{q}%"),RequestCase.title.ilike(f"%{q}%"),RequestCase.description.ilike(f"%{q}%"),User.full_name.ilike(f"%{q}%")))
        if selected_status in REQUEST_STATUSES: stmt=stmt.where(RequestCase.status == selected_status)
        if selected_category in REQUEST_CATEGORIES: stmt=stmt.where(RequestCase.category == selected_category)
        if overdue == "1": stmt=stmt.where(RequestCase.response_deadline.is_not(None),RequestCase.response_deadline < datetime.utcnow(),RequestCase.status.not_in(["resolved","case_closed"]))
        cutoff_map={"7d":7,"30d":30,"90d":90}
        if period in cutoff_map: stmt=stmt.where(RequestCase.created_at >= datetime.utcnow()-timedelta(days=cutoff_map[period]))
        order_map={"newest":RequestCase.created_at.desc(),"oldest":RequestCase.created_at.asc(),"deadline":RequestCase.response_deadline.asc().nullslast(),"updated":RequestCase.updated_at.desc()}
        rows=(await session.execute(stmt.order_by(order_map.get(sort,RequestCase.updated_at.desc())))).all()
        all_cases=(await session.scalars(select(RequestCase))).all(); counts={st:0 for st in REQUEST_STATUSES}
        for item in all_cases: counts[item.status]=counts.get(item.status,0)+1
        return templates.TemplateResponse(request=request,name="requests.html",context=ctx(request,rows=rows,counts=counts,selected_status=selected_status,selected_category=selected_category,statuses=REQUEST_STATUSES,categories=REQUEST_CATEGORIES,q=q,period=period,sort=sort,overdue=overdue))


@router.get("/admin/requests/{case_id}", response_class=HTMLResponse)
async def request_detail(request: Request, case_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        case = await session.get(RequestCase, case_id)
        if not case:
            return HTMLResponse("Звернення не знайдено", status_code=404)
        author = await session.get(User, case.user_id)
        assigned = await session.get(User, case.assigned_user_id) if case.assigned_user_id else None
        team = (await session.scalars(
            select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name.asc())
        )).all()
        message_rows = (await session.execute(
            select(RequestMessage, User)
            .outerjoin(User, User.id == RequestMessage.sender_user_id)
            .where(RequestMessage.case_id == case.id)
            .order_by(RequestMessage.created_at.asc(), RequestMessage.id.asc())
        )).all()
        return templates.TemplateResponse(
            request=request, name="request_detail.html",
            context=ctx(request, case=case, author=author, assigned=assigned, team=team, messages=message_rows,
                        statuses=REQUEST_STATUSES, categories=REQUEST_CATEGORIES,
                        priorities=REQUEST_PRIORITIES),
        )


@router.post("/admin/requests/{case_id}/photo")
async def request_photo_update(
    request: Request, case_id: int, remove_image: str | None = Form(None), photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    async with db.session_factory() as session:
        case = await session.get(RequestCase, case_id)
        if not case:
            return HTMLResponse("Звернення не знайдено", status_code=404)
        if remove_image:
            await delete_image(case.image_path)
            case.image_path = None
        img = await save_image(photo, "requests")
        if img:
            await delete_image(case.image_path)
            case.image_path = img
        case.updated_at = datetime.utcnow()
        await log_audit(session, "web_request_photo", actor_label=request.session.get("admin_name","web"), entity_type="request_case", entity_id=case.id, details="Оновлено фото звернення")
        await session.commit()
    return RedirectResponse(f"/admin/requests/{case_id}",303)


@router.post("/admin/requests/{case_id}/update")
async def request_update(
    request: Request,
    case_id: int,
    status: str = Form(...),
    category: str = Form("problem"),
    priority: str = Form("normal"),
    assigned_user_id: str = Form(""),
    response_deadline: str = Form(""),
    internal_note: str = Form(""),
):
    if r := guard(request): return r
    notify_tg: int | None = None
    notify_text = ""
    assigned_notify_tg: int | None = None
    assigned_notify_text = ""
    async with db.session_factory() as session:
        case = await session.get(RequestCase, case_id)
        if not case:
            return HTMLResponse("Звернення не знайдено", status_code=404)
        old_public = (case.status, case.category, case.priority, case.assigned_user_id, case.response_deadline)
        if status in REQUEST_STATUSES:
            case.status = status
        if category in REQUEST_CATEGORIES:
            case.category = category
        if priority in REQUEST_PRIORITIES:
            case.priority = priority
        case.assigned_user_id = opt_int(assigned_user_id)
        raw_deadline = response_deadline.strip()
        if raw_deadline:
            try:
                case.response_deadline = datetime.fromisoformat(raw_deadline)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Некоректний дедлайн відповіді") from exc
        else:
            case.response_deadline = None
        case.internal_note = internal_note.strip()
        case.updated_at = datetime.utcnow()
        case.resolved_at = datetime.utcnow() if case.status in {"resolved", "case_closed"} else None
        author = await session.get(User, case.user_id)
        assigned = await session.get(User, case.assigned_user_id) if case.assigned_user_id else None
        old_assigned_id = old_public[3]
        if assigned and case.assigned_user_id != old_assigned_id and assigned.tg_id:
            number = case.case_number or f"AMP-{case.created_at.year}-{case.id:04d}"
            deadline_text_assigned = case.response_deadline.strftime("%d.%m.%Y %H:%M") if case.response_deadline else "не встановлено"
            assigned_notify_tg = assigned.tg_id
            assigned_notify_text = (
                f"🆘 <b>Вас призначено відповідальним за звернення</b>\n\n"
                f"<b>{html_escape(number)} · {html_escape(case.title)}</b>\n"
                f"Пріоритет: <b>{html_escape(label(case.priority))}</b>\n"
                f"Дедлайн відповіді: <b>{html_escape(deadline_text_assigned)}</b>\n\n"
                "Натисніть «Детально», щоб переглянути кейс."
            )
        new_public = (case.status, case.category, case.priority, case.assigned_user_id, case.response_deadline)
        if author and new_public != old_public:
            number = case.case_number or f"AMP-{case.created_at.year}-{case.id:04d}"
            deadline_text = case.response_deadline.strftime("%d.%m.%Y %H:%M") if case.response_deadline else "не встановлено"
            notify_tg = author.tg_id
            notify_text = (
                f"🆘 <b>{html_escape(number)}</b> оновлено\n\n"
                f"📌 Статус: <b>{html_escape(request_status_label(case.status))}</b>\n"
                f"🗂 Категорія: {html_escape(label(case.category))}\n"
                f"⚡ Пріоритет: {html_escape(label(case.priority))}\n"
                f"👤 Відповідальний: {html_escape(assigned.full_name if assigned else 'ще не призначено')}\n"
                f"⏳ Дедлайн відповіді: {html_escape(deadline_text)}"
            )
            session.add(RequestMessage(
                case_id=case.id, sender_type="system", sender_user_id=None,
                body=f"Оновлено статус кейсу: {request_status_label(case.status)}. Дедлайн відповіді: {deadline_text}."
            ))
        await log_audit(
            session, "web_request_update", actor_label=request.session.get("admin_name", "web"),
            entity_type="request_case", entity_id=case.id,
            details=f"{case.case_number or case.id}: {request_status_label(case.status)}, {label(case.priority)}"
        )
        await session.commit()
    if notify_tg:
        await notify_telegram(notify_tg, notify_text, source="case", entity_type="request_case", entity_id=case_id)
    if assigned_notify_tg and assigned_notify_text:
        await notify_telegram(
            assigned_notify_tg, assigned_notify_text, source="case", entity_type="request_case", entity_id=case_id,
            button_text="👁 Детально", callback_data=f"assigned_request:{case_id}",
        )
    return RedirectResponse(f"/admin/requests/{case_id}", 303)


@router.post("/admin/requests/{case_id}/message")
async def request_add_message(
    request: Request,
    case_id: int,
    body: str = Form(""),
    photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    body = body.strip()
    image_path = await save_image(photo, "requests")
    if not body and not image_path:
        raise HTTPException(status_code=400, detail="Додайте текст повідомлення або вкладення")
    notify_tg = None
    notify_text = ""
    async with db.session_factory() as session:
        case = await session.get(RequestCase, case_id)
        if not case:
            if image_path: await delete_image(image_path)
            return HTMLResponse("Звернення не знайдено", status_code=404)
        if case.status == "case_closed":
            if image_path: await delete_image(image_path)
            raise HTTPException(status_code=409, detail="Закритий кейс не приймає нові повідомлення")
        admin_user = await session.scalar(
            select(User).where(User.role.in_([UserRole.SUPERADMIN.value, UserRole.ADMIN.value])).order_by(User.id.asc())
        )
        msg = RequestMessage(
            case_id=case.id,
            sender_type="admin",
            sender_user_id=admin_user.id if admin_user else None,
            body=body or "Вкладення від команди АМП",
            image_path=image_path,
        )
        session.add(msg)
        case.admin_response = body or case.admin_response
        case.updated_at = datetime.utcnow()
        author = await session.get(User, case.user_id)
        if author:
            number = case.case_number or f"AMP-{case.created_at.year}-{case.id:04d}"
            notify_tg = author.tg_id
            safe_body = html_escape(body) if body else "Команда АМП додала вкладення до звернення."
            notify_text = f"💬 <b>Нове повідомлення у {html_escape(number)}</b>\nСтатус: {html_escape(request_status_label(case.status))}\n\n{safe_body}"
        await log_audit(session, "web_request_message", actor_label=request.session.get("admin_name", "web"), entity_type="request_case", entity_id=case.id, details=f"Додано повідомлення до {case.case_number or case.id}")
        await session.commit()
    if notify_tg:
        await notify_telegram(notify_tg, notify_text, source="case", entity_type="request_case", entity_id=case_id)
    return RedirectResponse(f"/admin/requests/{case_id}", 303)

