from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/broadcasts", response_class=HTMLResponse)
async def broadcasts_page(request: Request):
    if r := guard_permission(request, "broadcast.send"): return r
    async with db.session_factory() as session:
        context = await _broadcast_form_context(session, request)
        return templates.TemplateResponse(request=request, name="broadcasts.html", context=context)


@router.post("/admin/broadcasts/templates/create")
async def broadcast_template_create(
    request: Request,
    title: str = Form(...),
    text: str = Form(...),
):
    if r := guard_permission(request, "broadcast.send"): return r
    title = title.strip()
    text = text.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Вкажіть назву шаблону.")
    if len(title) > 120:
        raise HTTPException(status_code=400, detail="Назва шаблону завелика. Максимум — 120 символів.")
    if not text:
        raise HTTPException(status_code=400, detail="Вкажіть текст шаблону.")
    if len(text) > 3800:
        raise HTTPException(status_code=400, detail="Текст шаблону завеликий. Максимум — 3800 символів.")
    async with db.session_factory() as session:
        row = BroadcastTemplate(
            title=title, text=text, active=True,
            created_by_label=request.session.get("admin_name", "superadmin"),
        )
        session.add(row)
        await session.flush()
        await log_audit(
            session, "web_broadcast_template_create",
            actor_label=request.session.get("admin_name", "superadmin"),
            entity_type="broadcast_template", entity_id=row.id,
            details=f"Створено власний шаблон «{row.title}».",
        )
        await session.commit()
    return RedirectResponse("/admin/broadcasts#customTemplates", status_code=303)


@router.post("/admin/broadcasts/templates/{template_id}/update")
async def broadcast_template_update(
    request: Request, template_id: int,
    title: str = Form(...), text: str = Form(...), active: str | None = Form(None),
):
    if r := guard_permission(request, "broadcast.send"): return r
    title = title.strip()
    text = text.strip()
    if not title or not text:
        raise HTTPException(status_code=400, detail="Назва і текст шаблону є обов’язковими.")
    if len(title) > 120 or len(text) > 3800:
        raise HTTPException(status_code=400, detail="Перевищено допустиму довжину назви або тексту шаблону.")
    async with db.session_factory() as session:
        row = await session.get(BroadcastTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="Шаблон не знайдено.")
        row.title = title
        row.text = text
        row.active = bool(active)
        row.updated_at = clock.storage_utc()
        await log_audit(
            session, "web_broadcast_template_update",
            actor_label=request.session.get("admin_name", "superadmin"),
            entity_type="broadcast_template", entity_id=row.id,
            details=f"Оновлено власний шаблон «{row.title}»; активний={row.active}.",
        )
        await session.commit()
    return RedirectResponse("/admin/broadcasts#customTemplates", status_code=303)


@router.post("/admin/broadcasts/templates/{template_id}/delete")
async def broadcast_template_delete(request: Request, template_id: int):
    if r := guard_permission(request, "broadcast.send"): return r
    async with db.session_factory() as session:
        row = await session.get(BroadcastTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="Шаблон не знайдено.")
        title = row.title
        await session.delete(row)
        await log_audit(
            session, "web_broadcast_template_delete",
            actor_label=request.session.get("admin_name", "superadmin"),
            entity_type="broadcast_template", entity_id=template_id,
            details=f"Видалено власний шаблон «{title}».",
        )
        await session.commit()
    return RedirectResponse("/admin/broadcasts#customTemplates", status_code=303)


@router.post("/admin/broadcasts/preview", response_class=HTMLResponse)
async def broadcasts_preview(
    request: Request,
    audience_type: str = Form(...),
    settlement_value: str = Form(""),
    event_value: str = Form(""),
    age_min: str = Form(""),
    age_max: str = Form(""),
    inactive_days: str = Form("30"),
    template_code: str = Form(""),
    message_text: str = Form(""),
):
    if r := guard_permission(request, "broadcast.send"): return r
    amin = opt_int(age_min)
    amax = opt_int(age_max)
    inactive = opt_int(inactive_days) or 30
    text = _clean_broadcast_text(message_text, template_code)
    audience_value = settlement_value.strip() if audience_type == "settlement" else event_value.strip() if audience_type == "event" else ""
    if audience_type == "age_group" and (amin is None or amax is None or amin < 0 or amax > 120):
        raise HTTPException(status_code=400, detail="Для вікової групи вкажіть коректний мінімальний і максимальний вік.")
    if audience_type == "settlement" and not audience_value.strip():
        raise HTTPException(status_code=400, detail="Оберіть населений пункт.")
    if audience_type == "event" and not audience_value.strip():
        raise HTTPException(status_code=400, detail="Оберіть подію.")

    async with db.session_factory() as session:
        recipients = await resolve_broadcast_audience(
            session, audience_type,
            audience_value=audience_value,
            age_min=amin,
            age_max=amax,
            inactive_days=inactive,
        )
        description = await audience_description(
            session, audience_type,
            audience_value=audience_value,
            age_min=amin,
            age_max=amax,
            inactive_days=inactive,
        )
        sample_user = recipients[0] if recipients else None
        preview_text = personalize_message(text, sample_user) if sample_user else text
        preview = {
            "count": len(recipients),
            "description": description,
            "names": [u.full_name for u in recipients[:12]],
            "text": preview_text,
        }
        form_data = {
            "audience_type": audience_type,
            "audience_value": audience_value,
            "age_min": age_min,
            "age_max": age_max,
            "inactive_days": str(inactive),
            "template_code": template_code,
            "message_text": text,
        }
        context = await _broadcast_form_context(session, request, preview=preview, form_data=form_data)
        return templates.TemplateResponse(request=request, name="broadcasts.html", context=context)


@router.post("/admin/broadcasts/send")
async def broadcasts_send(
    request: Request,
    audience_type: str = Form(...),
    audience_value: str = Form(""),
    age_min: str = Form(""),
    age_max: str = Form(""),
    inactive_days: str = Form("30"),
    template_code: str = Form(""),
    message_text: str = Form(...),
):
    if r := guard_permission(request, "broadcast.send"): return r
    amin = opt_int(age_min)
    amax = opt_int(age_max)
    inactive = opt_int(inactive_days) or 30
    text = _clean_broadcast_text(message_text, template_code)

    async with db.session_factory() as session:
        recipients = await resolve_broadcast_audience(
            session, audience_type,
            audience_value=audience_value,
            age_min=amin,
            age_max=amax,
            inactive_days=inactive,
        )
        if not recipients:
            raise HTTPException(status_code=400, detail="За обраними умовами немає одержувачів. Поверніться і змініть фільтр.")
        description = await audience_description(
            session, audience_type,
            audience_value=audience_value,
            age_min=amin,
            age_max=amax,
            inactive_days=inactive,
        )
        campaign = BroadcastCampaign(
            source="web",
            author_label=request.session.get("admin_name", "superadmin"),
            audience_type=audience_type,
            audience_value=audience_value.strip() or None,
            age_min=amin,
            age_max=amax,
            inactive_days=inactive if audience_type == "inactive" else None,
            template_code=template_code or None,
            message_text=text,
            status="queued",
            recipient_count=len(recipients),
        )
        session.add(campaign)
        await session.flush()
        for user in recipients:
            session.add(BroadcastRecipient(
                campaign_id=campaign.id,
                user_id=user.id,
                recipient_name=user.full_name,
                recipient_tg_id=user.tg_id,
                status="pending",
            ))
        await log_audit(
            session,
            "web_broadcast_queued",
            actor_label=request.session.get("admin_name", "superadmin"),
            entity_type="broadcast",
            entity_id=campaign.id,
            details=f"Створено розсилку для аудиторії «{description}». Одержувачів: {len(recipients)}.",
        )
        await session.commit()
        campaign_id = campaign.id

    _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/broadcasts/{campaign_id}", status_code=303)


@router.get("/admin/broadcasts/{campaign_id}", response_class=HTMLResponse)
async def broadcast_detail(request: Request, campaign_id: int):
    if r := guard_permission(request, "broadcast.send"): return r
    async with db.session_factory() as session:
        campaign = await session.get(BroadcastCampaign, campaign_id)
        if not campaign:
            return HTMLResponse("Розсилку не знайдено", status_code=404)
        recipients = (await session.scalars(
            select(BroadcastRecipient)
            .where(BroadcastRecipient.campaign_id == campaign_id)
            .order_by(BroadcastRecipient.status.asc(), BroadcastRecipient.recipient_name.asc())
        )).all()
        description = await audience_description(
            session,
            campaign.audience_type,
            audience_value=campaign.audience_value,
            age_min=campaign.age_min,
            age_max=campaign.age_max,
            inactive_days=campaign.inactive_days,
        )
        return templates.TemplateResponse(
            request=request,
            name="broadcast_detail.html",
            context=ctx(request, campaign=campaign, recipients=recipients, audience_description_text=description),
        )

