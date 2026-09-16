from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.opportunity_matching import OPPORTUNITY_INTERESTS, refresh_matches_for_opportunity
from app.models import OpportunityMatch
from app.content_views import content_view_stats

router = APIRouter()


@router.get("/admin/opportunities", response_class=HTMLResponse)
async def opportunities_page(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "deadline"):
    if r := guard(request): return r
    async with db.session_factory() as session:
        stmt = select(Opportunity)
        if q:
            stmt = stmt.where(or_(
                Opportunity.title.ilike(f"%{q}%"), Opportunity.description.ilike(f"%{q}%"),
                Opportunity.direction.ilike(f"%{q}%"), Opportunity.target_settlements.ilike(f"%{q}%"),
            ))
        if status == "active": stmt = stmt.where(Opportunity.active == True)  # noqa: E712
        elif status == "inactive": stmt = stmt.where(Opportunity.active == False)  # noqa: E712
        if type: stmt = stmt.where(Opportunity.kind == type)
        cutoff_map = {"7d": 7, "30d": 30, "90d": 90}
        if period in cutoff_map:
            stmt = stmt.where(Opportunity.created_at >= datetime.utcnow() - timedelta(days=cutoff_map[period]))
        order_map = {"newest": Opportunity.created_at.desc(), "oldest": Opportunity.created_at.asc(), "title": Opportunity.title.asc(), "deadline": Opportunity.deadline.asc().nullslast()}
        items = list((await session.scalars(stmt.order_by(order_map.get(sort, Opportunity.deadline.asc().nullslast())))).all())
        counts = dict((await session.execute(select(OpportunityInterest.opportunity_id, func.count(OpportunityInterest.id)).where(OpportunityInterest.status == "interested").group_by(OpportunityInterest.opportunity_id))).all())
        match_counts = dict((await session.execute(select(OpportunityMatch.opportunity_id, func.count(OpportunityMatch.id)).where(OpportunityMatch.status.in_(["matched", "notified"])).group_by(OpportunityMatch.opportunity_id))).all())
        view_stats = await content_view_stats(session, "opportunity", [item.id for item in items])
        kinds = sorted(set((await session.scalars(select(Opportunity.kind).distinct())).all()))
        return templates.TemplateResponse(request=request, name="opportunities.html", context=ctx(
            request, items=items, interest_counts=counts, match_counts=match_counts, view_stats=view_stats,
            q=q, status=status, period=period, type=type, sort=sort, kinds=kinds,
            opportunity_interests=OPPORTUNITY_INTERESTS,
        ))


@router.post("/admin/opportunities/create")
async def opportunity_create(
    request: Request, title: str = Form(...), kind: str = Form("можливість"), direction: str = Form("Інше"),
    format: str = Form("Онлайн/офлайн"), age_min: str = Form(""), age_max: str = Form(""),
    deadline: str = Form(""), url: str = Form(""), description: str = Form(""),
    target_settlements: str = Form(""), active: str | None = Form(None),
    photo: UploadFile | None = File(None),
):
    if r := guard(request): return r
    def oi(v): return int(v) if v.strip().isdigit() else None
    dl = datetime.fromisoformat(deadline) if deadline else None
    image_path = await save_image(photo, "opportunities") if photo and photo.filename else None
    async with db.session_factory() as session:
        item = Opportunity(
            title=title.strip(), kind=kind.strip() or "можливість", direction=direction.strip() or "Інше",
            format=format.strip() or "Онлайн/офлайн", age_min=oi(age_min), age_max=oi(age_max),
            deadline=dl, url=url.strip() or None, description=description.strip(), active=bool(active),
            target_settlements=target_settlements.strip() or None, image_path=image_path, updated_at=datetime.utcnow(),
        )
        session.add(item); await session.flush()
        await log_audit(session, "web_opportunity_create", actor_label=request.session.get("admin_name", "web"), entity_type="opportunity", entity_id=item.id, details=item.title)
        if item.active:
            await refresh_matches_for_opportunity(session, item)
        await session.commit()
    return RedirectResponse("/admin/opportunities", 303)


@router.post("/admin/opportunities/{opportunity_id}/update")
async def opportunity_update(request: Request, opportunity_id: int):
    if r := guard(request): return r
    form = await request.form()
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if not item: raise HTTPException(status_code=404, detail="Можливість не знайдено")
        item.title = str(form.get("title") or "").strip() or item.title
        item.kind = str(form.get("kind") or "можливість").strip()
        item.direction = str(form.get("direction") or "Інше").strip()
        item.format = str(form.get("format") or "Онлайн/офлайн").strip()
        item.description = str(form.get("description") or "").strip()
        item.url = str(form.get("url") or "").strip() or None
        item.target_settlements = str(form.get("target_settlements") or "").strip() or None
        for key in ("age_min", "age_max"):
            raw = str(form.get(key) or "").strip(); setattr(item, key, int(raw) if raw.isdigit() else None)
        raw = str(form.get("deadline") or "").strip()
        item.deadline = datetime.fromisoformat(raw) if raw else None
        photo = form.get("photo")
        if form.get("remove_image") and item.image_path:
            await delete_image(item.image_path)
            item.image_path = None
        if photo and getattr(photo, "filename", ""):
            new_image = await save_image(photo, "opportunities")
            if new_image:
                if item.image_path:
                    await delete_image(item.image_path)
                item.image_path = new_image
        item.active = bool(form.get("active")); item.updated_at = datetime.utcnow()
        await log_audit(session, "web_opportunity_update", actor_label=request.session.get("admin_name", "web"), entity_type="opportunity", entity_id=item.id, details=item.title)
        # Rebuild pending matches after every eligibility-related edit.
        await session.execute(delete(OpportunityMatch).where(OpportunityMatch.opportunity_id == item.id, OpportunityMatch.notified_at.is_(None)))
        if item.active:
            await refresh_matches_for_opportunity(session, item)
        await session.commit()
    return RedirectResponse("/admin/opportunities", 303)


@router.post("/admin/opportunities/{opportunity_id}/delete")
async def opportunity_delete(request: Request, opportunity_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if item:
            image_path = item.image_path
            await session.execute(delete(OpportunityInterest).where(OpportunityInterest.opportunity_id == item.id))
            await session.execute(delete(OpportunityMatch).where(OpportunityMatch.opportunity_id == item.id))
            await log_audit(session, "web_opportunity_delete", actor_label=request.session.get("admin_name", "web"), entity_type="opportunity", entity_id=item.id, details=item.title)
            await session.delete(item); await session.commit()
            if image_path:
                await delete_image(image_path)
    return RedirectResponse("/admin/opportunities", 303)
