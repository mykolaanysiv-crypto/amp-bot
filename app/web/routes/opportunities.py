from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
from app.web.dependencies import (
    File, Form, HTMLResponse, HTTPException, Opportunity, OpportunityInterest,
    RedirectResponse, Request, UploadFile, User, ctx, datetime, db, delete,
    delete_image, func, guard, log_audit, or_, save_image, select, settings,
    templates, timedelta,
)
from app.opportunity_matching import OPPORTUNITY_INTERESTS, refresh_matches_for_opportunity
from app.models import OpportunityMatch
from app.content_views import content_view_stat, content_view_stats
from app.opportunity_utils import deadline_urgency, opportunity_sort_key

router = APIRouter()


@router.get("/admin/opportunities", response_class=HTMLResponse)
async def opportunities_page(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "auto"):
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        stmt = select(Opportunity)
        if q:
            stmt = stmt.where(or_(
                Opportunity.title.ilike(f"%{q}%"), Opportunity.description.ilike(f"%{q}%"),
                Opportunity.direction.ilike(f"%{q}%"), Opportunity.target_settlements.ilike(f"%{q}%"),
            ))
        if status == "active":
            stmt = stmt.where(Opportunity.active == True)  # noqa: E712
        elif status == "inactive":
            stmt = stmt.where(Opportunity.active == False)  # noqa: E712
        if type:
            stmt = stmt.where(Opportunity.kind == type)
        cutoff_map = {"7d": 7, "30d": 30, "90d": 90}
        if period in cutoff_map:
            stmt = stmt.where(Opportunity.created_at >= clock.storage_utc() - timedelta(days=cutoff_map[period]))
        order_map = {
            "newest": Opportunity.created_at.desc(),
            "oldest": Opportunity.created_at.asc(),
            "title": Opportunity.title.asc(),
            "deadline": Opportunity.deadline.asc().nullslast(),
        }
        if sort == "auto":
            items = list((await session.scalars(stmt)).all())
            items.sort(key=opportunity_sort_key)
        else:
            items = list((await session.scalars(stmt.order_by(order_map.get(sort, Opportunity.deadline.asc().nullslast())))).all())
        counts = dict((await session.execute(
            select(OpportunityInterest.opportunity_id, func.count(OpportunityInterest.id))
            .where(OpportunityInterest.status == "interested")
            .group_by(OpportunityInterest.opportunity_id)
        )).all())
        match_counts = dict((await session.execute(
            select(OpportunityMatch.opportunity_id, func.count(OpportunityMatch.id))
            .where(OpportunityMatch.status.in_(["matched", "notified"]))
            .group_by(OpportunityMatch.opportunity_id)
        )).all())
        view_stats = await content_view_stats(session, "opportunity", [item.id for item in items])
        opportunity_states = {item.id: deadline_urgency(item) for item in items}
        kinds = sorted(set((await session.scalars(select(Opportunity.kind).distinct())).all()))
        return templates.TemplateResponse(request=request, name="opportunities.html", context=ctx(
            request, items=items, interest_counts=counts, match_counts=match_counts, view_stats=view_stats,
            opportunity_states=opportunity_states, q=q, status=status, period=period, type=type, sort=sort,
            kinds=kinds, opportunity_interests=OPPORTUNITY_INTERESTS,
        ))


@router.get("/admin/opportunities/{opportunity_id}", response_class=HTMLResponse)
async def opportunity_detail(request: Request, opportunity_id: int):
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if not item:
            raise HTTPException(status_code=404, detail="Можливість не знайдено")

        interest_rows = list((await session.execute(
            select(OpportunityInterest, User)
            .join(User, User.id == OpportunityInterest.user_id)
            .where(OpportunityInterest.opportunity_id == item.id)
            .order_by(OpportunityInterest.updated_at.desc(), OpportunityInterest.id.desc())
        )).all())
        match_rows = list((await session.execute(
            select(OpportunityMatch, User)
            .join(User, User.id == OpportunityMatch.user_id)
            .where(OpportunityMatch.opportunity_id == item.id)
            .order_by(OpportunityMatch.score.desc(), OpportunityMatch.updated_at.desc())
        )).all())
        view_stat = await content_view_stat(session, "opportunity", item.id)
        state = deadline_urgency(item)

        interested_count = sum(1 for row, _ in interest_rows if row.status == "interested")
        not_interested_count = sum(1 for row, _ in interest_rows if row.status == "not_interested")
        active_matches = [row for row, _ in match_rows if row.status in {"matched", "notified"}]
        notified_count = sum(1 for row in active_matches if row.notified_at is not None or row.status == "notified")
        avg_score = round(sum(int(row.score or 0) for row in active_matches) / len(active_matches), 1) if active_matches else 0.0
        unique_views = int(view_stat.get("unique", 0))
        analytics = {
            "interested": interested_count,
            "not_interested": not_interested_count,
            "matches": len(active_matches),
            "notified": notified_count,
            "avg_score": avg_score,
            "views": int(view_stat.get("views", 0)),
            "unique_views": unique_views,
            "repeat_views": max(0, int(view_stat.get("views", 0)) - unique_views),
            "interest_rate": round(interested_count * 100 / unique_views, 1) if unique_views else 0.0,
        }
        share_url = f"{settings.public_base_url.rstrip('/')}/opportunity/{item.id}"
        return templates.TemplateResponse(
            request=request,
            name="opportunity_detail.html",
            context=ctx(
                request,
                item=item,
                state=state,
                analytics=analytics,
                interest_rows=interest_rows,
                match_rows=match_rows,
                share_url=share_url,
                opportunity_interests=OPPORTUNITY_INTERESTS,
            ),
        )


@router.get("/opportunity/{opportunity_id}", response_class=HTMLResponse)
async def opportunity_public(request: Request, opportunity_id: int):
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if not item or not item.active:
            raise HTTPException(status_code=404, detail="Можливість не знайдено")
        state = deadline_urgency(item)
        share_url = f"{settings.public_base_url.rstrip('/')}/opportunity/{item.id}"
        return templates.TemplateResponse(
            request=request,
            name="opportunity_public.html",
            context={"request": request, "item": item, "state": state, "share_url": share_url},
        )


@router.post("/admin/opportunities/create")
async def opportunity_create(
    request: Request, title: str = Form(...), kind: str = Form("можливість"), direction: str = Form("Інше"),
    format: str = Form("Онлайн/офлайн"), age_min: str = Form(""), age_max: str = Form(""),
    deadline: str = Form(""), url: str = Form(""), description: str = Form(""),
    target_settlements: str = Form(""), active: str | None = Form(None),
    photo: UploadFile | None = File(None),
):
    if r := guard(request):
        return r

    def oi(v: str):
        return int(v) if v.strip().isdigit() else None

    dl = datetime.fromisoformat(deadline) if deadline else None
    image_path = await save_image(photo, "opportunities") if photo and photo.filename else None
    async with db.session_factory() as session:
        item = Opportunity(
            title=title.strip(), kind=kind.strip() or "можливість", direction=direction.strip() or "Інше",
            format=format.strip() or "Онлайн/офлайн", age_min=oi(age_min), age_max=oi(age_max),
            deadline=dl, url=url.strip() or None, description=description.strip(), active=bool(active),
            target_settlements=target_settlements.strip() or None, image_path=image_path, updated_at=clock.storage_utc(),
        )
        session.add(item)
        await session.flush()
        await log_audit(
            session, "web_opportunity_create", actor_label=request.session.get("admin_name", "web"),
            entity_type="opportunity", entity_id=item.id, details=item.title,
        )
        if item.active:
            await refresh_matches_for_opportunity(session, item)
        await session.commit()
        item_id = item.id
    return RedirectResponse(f"/admin/opportunities/{item_id}", 303)


@router.post("/admin/opportunities/{opportunity_id}/update")
async def opportunity_update(request: Request, opportunity_id: int):
    if r := guard(request):
        return r
    form = await request.form()
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if not item:
            raise HTTPException(status_code=404, detail="Можливість не знайдено")
        item.title = str(form.get("title") or "").strip() or item.title
        item.kind = str(form.get("kind") or "можливість").strip()
        item.direction = str(form.get("direction") or "Інше").strip()
        item.format = str(form.get("format") or "Онлайн/офлайн").strip()
        item.description = str(form.get("description") or "").strip()
        item.url = str(form.get("url") or "").strip() or None
        item.target_settlements = str(form.get("target_settlements") or "").strip() or None
        for key in ("age_min", "age_max"):
            raw = str(form.get(key) or "").strip()
            setattr(item, key, int(raw) if raw.isdigit() else None)
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
        item.active = bool(form.get("active"))
        item.updated_at = clock.storage_utc()
        await log_audit(
            session, "web_opportunity_update", actor_label=request.session.get("admin_name", "web"),
            entity_type="opportunity", entity_id=item.id, details=item.title,
        )
        await session.execute(delete(OpportunityMatch).where(
            OpportunityMatch.opportunity_id == item.id,
            OpportunityMatch.notified_at.is_(None),
        ))
        if item.active:
            await refresh_matches_for_opportunity(session, item)
        await session.commit()
    return RedirectResponse(f"/admin/opportunities/{opportunity_id}", 303)


@router.post("/admin/opportunities/{opportunity_id}/toggle")
async def opportunity_toggle(request: Request, opportunity_id: int):
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if not item:
            raise HTTPException(status_code=404, detail="Можливість не знайдено")
        item.active = not bool(item.active)
        item.updated_at = clock.storage_utc()
        if item.active:
            await refresh_matches_for_opportunity(session, item)
        await log_audit(
            session, "web_opportunity_toggle", actor_label=request.session.get("admin_name", "web"),
            entity_type="opportunity", entity_id=item.id, details=f"active={item.active}; {item.title}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/opportunities/{opportunity_id}", 303)


@router.post("/admin/opportunities/{opportunity_id}/refresh-matches")
async def opportunity_refresh_matches(request: Request, opportunity_id: int):
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if not item:
            raise HTTPException(status_code=404, detail="Можливість не знайдено")
        await session.execute(delete(OpportunityMatch).where(
            OpportunityMatch.opportunity_id == item.id,
            OpportunityMatch.notified_at.is_(None),
        ))
        if item.active:
            await refresh_matches_for_opportunity(session, item)
        await log_audit(
            session, "web_opportunity_matches_refresh", actor_label=request.session.get("admin_name", "web"),
            entity_type="opportunity", entity_id=item.id, details=item.title,
        )
        await session.commit()
    return RedirectResponse(f"/admin/opportunities/{opportunity_id}", 303)


@router.post("/admin/opportunities/{opportunity_id}/delete")
async def opportunity_delete(request: Request, opportunity_id: int):
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        item = await session.get(Opportunity, opportunity_id)
        if item:
            image_path = item.image_path
            await session.execute(delete(OpportunityInterest).where(OpportunityInterest.opportunity_id == item.id))
            await session.execute(delete(OpportunityMatch).where(OpportunityMatch.opportunity_id == item.id))
            await log_audit(
                session, "web_opportunity_delete", actor_label=request.session.get("admin_name", "web"),
                entity_type="opportunity", entity_id=item.id, details=item.title,
            )
            await session.delete(item)
            await session.commit()
            if image_path:
                await delete_image(image_path)
    return RedirectResponse("/admin/opportunities", 303)
