from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote
import calendar as pycalendar

from fastapi import APIRouter, Query
from sqlalchemy import and_
from app.web.app import *  # noqa: F401,F403 - shared web dependencies
from app.runtime_config import RULE_SPECS, SECTIONS, get_runtime_values, set_runtime_values

router = APIRouter()


def _amp_id_query(raw: str) -> int | None:
    text = (raw or "").strip().upper()
    if text.startswith("АМП-"):
        text = text[4:]
    elif text.startswith("AMP-"):
        text = text[4:]
    try:
        return int(text) if text.isdigit() else None
    except ValueError:
        return None


@router.get("/admin/search", response_class=HTMLResponse)
async def global_search(request: Request, q: str = ""):
    if r := guard(request):
        return r
    q = (q or "").strip()
    groups: dict[str, list[dict]] = {
        "Учасники": [], "Події": [], "Кейси": [], "Ідеї": [], "Активності": []
    }
    perms = web_permissions(request)
    can_users = "participants.view" in perms
    can_events = bool(perms & {"events.create", "events.edit", "events.delete"})
    can_cases = "cases.manage" in perms
    can_ideas = "ideas.manage" in perms
    can_quests = "quests.manage" in perms
    can_tasks = "volunteer.manage" in perms
    can_activities = "activities.manage" in perms
    can_opportunities = "opportunities.manage" in perms
    can_surveys = "surveys.manage" in perms

    if q:
        like = f"%{q}%"
        amp_id = _amp_id_query(q)
        async with db.session_factory() as session:
            if can_users:
                user_filters = [User.full_name.ilike(like), User.username.ilike(like), User.settlement.ilike(like)]
                if amp_id is not None:
                    user_filters.append(User.id == amp_id)
                if is_superadmin(request):
                    user_filters.extend([User.phone.ilike(like), User.email.ilike(like)])
                users = (await session.scalars(
                    select(User).where(or_(*user_filters)).order_by(User.full_name.asc()).limit(15)
                )).all()
                groups["Учасники"] = [
                    {"title": u.full_name, "meta": f"АМП-{u.id:04d} • {label(u.role)} • {label(u.status)}", "url": f"/admin/users/{u.id}"}
                    for u in users
                ]

            if can_events:
                events = (await session.scalars(
                    select(Event).where(Event.title.ilike(like)).order_by(Event.starts_at.desc()).limit(12)
                )).all()
                groups["Події"] = [
                    {"title": e.title, "meta": f"{e.starts_at.strftime('%d.%m.%Y %H:%M')} • {lifecycle_status_label(e.status)}", "url": f"/admin/events/{e.id}"}
                    for e in events
                ]

            if can_cases:
                cases = (await session.scalars(
                    select(RequestCase).where(or_(RequestCase.case_number.ilike(like), RequestCase.title.ilike(like), RequestCase.description.ilike(like)))
                    .order_by(RequestCase.updated_at.desc()).limit(12)
                )).all()
                groups["Кейси"] = [
                    {"title": c.case_number or f"AMP-{c.created_at.year}-{c.id:04d}", "meta": f"{c.title} • {request_status_label(c.status)}", "url": f"/admin/requests/{c.id}"}
                    for c in cases
                ]

            if can_ideas:
                ideas = (await session.scalars(
                    select(Idea).where(or_(Idea.title.ilike(like), Idea.problem.ilike(like), Idea.description.ilike(like)))
                    .order_by(Idea.updated_at.desc()).limit(12)
                )).all()
                groups["Ідеї"] = [
                    {"title": i.title, "meta": idea_status_label(i.status), "url": f"/admin/ideas/{i.id}"}
                    for i in ideas
                ]

            activity_results: list[dict] = []
            if can_quests:
                quests = (await session.scalars(select(Quest).where(or_(Quest.title.ilike(like), Quest.description.ilike(like))).order_by(Quest.starts_at.desc()).limit(8))).all()
                activity_results.extend({"title": qst.title, "meta": "🎯 Квест", "url": f"/admin/quests/{qst.id}"} for qst in quests)
            if can_tasks:
                tasks = (await session.scalars(select(VolunteerTask).where(or_(VolunteerTask.title.ilike(like), VolunteerTask.description.ilike(like))).order_by(VolunteerTask.created_at.desc()).limit(8))).all()
                activity_results.extend({"title": t.title, "meta": "✅ Волонтерська задача", "url": f"/admin/tasks/{t.id}"} for t in tasks)
            if can_activities:
                activity_types = (await session.scalars(select(ActivityType).where(or_(ActivityType.title.ilike(like), ActivityType.description.ilike(like))).order_by(ActivityType.title.asc()).limit(8))).all()
                activity_results.extend({"title": a.title, "meta": "⚡ Активність", "url": f"/admin/activities?type={a.id}"} for a in activity_types)
            if can_opportunities:
                opportunities = (await session.scalars(select(Opportunity).where(or_(Opportunity.title.ilike(like), Opportunity.description.ilike(like))).order_by(Opportunity.created_at.desc()).limit(8))).all()
                activity_results.extend({"title": o.title, "meta": f"🌍 {o.kind}", "url": "/admin/opportunities?q=" + quote(o.title)} for o in opportunities)
            if can_surveys:
                surveys = (await session.scalars(select(Survey).where(or_(Survey.title.ilike(like), Survey.description.ilike(like))).order_by(Survey.created_at.desc()).limit(8))).all()
                activity_results.extend({"title": s.title, "meta": "📋 Опитування", "url": f"/admin/surveys/{s.id}"} for s in surveys)
            groups["Активності"] = activity_results[:24]

    return templates.TemplateResponse(
        request=request,
        name="global_search.html",
        context=ctx(request, q=q, groups=groups, total=sum(len(v) for v in groups.values())),
    )


@router.get("/admin/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, view: str = "month", date_value: str = Query("", alias="date")):
    if r := guard(request):
        return r
    view = view if view in {"day", "week", "month"} else "month"
    try:
        selected = date.fromisoformat(date_value) if date_value else date.today()
    except ValueError:
        selected = date.today()

    if view == "day":
        period_start = selected
        period_end = selected
        prev_date = selected - timedelta(days=1)
        next_date = selected + timedelta(days=1)
    elif view == "week":
        period_start = selected - timedelta(days=selected.weekday())
        period_end = period_start + timedelta(days=6)
        prev_date = selected - timedelta(days=7)
        next_date = selected + timedelta(days=7)
    else:
        month_start = selected.replace(day=1)
        month_last = pycalendar.monthrange(selected.year, selected.month)[1]
        month_end = selected.replace(day=month_last)
        period_start = month_start - timedelta(days=month_start.weekday())
        period_end = month_end + timedelta(days=(6 - month_end.weekday()))
        prev_date = (month_start - timedelta(days=1)).replace(day=1)
        if selected.month == 12:
            next_date = date(selected.year + 1, 1, 1)
        else:
            next_date = date(selected.year, selected.month + 1, 1)

    start_dt = datetime.combine(period_start, datetime.min.time())
    end_dt = datetime.combine(period_end, datetime.max.time())
    items: list[dict] = []

    def add_item(when, icon, title, kind, css, url, meta=""):
        if not when:
            return
        items.append({
            "when": when, "icon": icon, "title": title, "type": kind,
            "css": css, "url": url, "meta": meta,
        })

    async with db.session_factory() as session:
        events = (await session.scalars(select(Event).where(Event.starts_at >= start_dt, Event.starts_at <= end_dt).order_by(Event.starts_at.asc()))).all()
        quests = (await session.scalars(select(Quest).where(or_(
            and_(Quest.starts_at >= start_dt, Quest.starts_at <= end_dt),
            and_(Quest.ends_at.is_not(None), Quest.ends_at >= start_dt, Quest.ends_at <= end_dt),
        )).order_by(Quest.starts_at.asc()))).all()
        tasks = (await session.scalars(select(VolunteerTask).where(VolunteerTask.deadline.is_not(None), VolunteerTask.deadline >= start_dt, VolunteerTask.deadline <= end_dt).order_by(VolunteerTask.deadline.asc()))).all()
        surveys = (await session.scalars(select(Survey).where(or_(
            and_(Survey.starts_at.is_not(None), Survey.starts_at >= start_dt, Survey.starts_at <= end_dt),
            and_(Survey.ends_at.is_not(None), Survey.ends_at >= start_dt, Survey.ends_at <= end_dt),
        )).order_by(Survey.created_at.asc()))).all()
        opportunities = (await session.scalars(select(Opportunity).where(Opportunity.deadline.is_not(None), Opportunity.deadline >= start_dt, Opportunity.deadline <= end_dt).order_by(Opportunity.deadline.asc()))).all()
        cases = (await session.scalars(select(RequestCase).where(RequestCase.response_deadline.is_not(None), RequestCase.response_deadline >= start_dt, RequestCase.response_deadline <= end_dt).order_by(RequestCase.response_deadline.asc()))).all()
        ideas = (await session.scalars(select(Idea).where(Idea.implementation_deadline.is_not(None), Idea.implementation_deadline >= start_dt, Idea.implementation_deadline <= end_dt).order_by(Idea.implementation_deadline.asc()))).all()
        freezes = (await session.execute(
            select(StreakFreeze, User).join(User, User.id == StreakFreeze.user_id).where(
                StreakFreeze.starts_at <= end_dt,
                StreakFreeze.ends_at >= start_dt,
            ).order_by(StreakFreeze.starts_at.asc())
        )).all()

    for e in events:
        add_item(e.starts_at, "📅", e.title, "Подія", "event", f"/admin/events/{e.id}", lifecycle_status_label(e.status))
    for q in quests:
        if q.starts_at and start_dt <= q.starts_at <= end_dt:
            add_item(q.starts_at, "🎯", q.title, "Старт квесту", "quest", f"/admin/quests/{q.id}", lifecycle_status_label(q.status))
        if q.ends_at and start_dt <= q.ends_at <= end_dt:
            add_item(q.ends_at, "🎯", q.title, "Дедлайн квесту", "quest", f"/admin/quests/{q.id}", lifecycle_status_label(q.status))
    for t in tasks:
        add_item(t.deadline, "✅", t.title, "Дедлайн задачі", "task", f"/admin/tasks/{t.id}", lifecycle_status_label(t.status))
    for srow in surveys:
        if srow.starts_at and start_dt <= srow.starts_at <= end_dt:
            add_item(srow.starts_at, "📋", srow.title, "Старт опитування", "survey", f"/admin/surveys/{srow.id}", label(srow.status))
        if srow.ends_at and start_dt <= srow.ends_at <= end_dt:
            add_item(srow.ends_at, "📋", srow.title, "Дедлайн опитування", "survey", f"/admin/surveys/{srow.id}", label(srow.status))
    for o in opportunities:
        add_item(o.deadline, "🌍", o.title, "Дедлайн можливості", "opportunity", "/admin/opportunities?q=" + quote(o.title), o.kind)
    for c in cases:
        add_item(c.response_deadline, "🆘", c.title, "Дедлайн кейсу", "case", f"/admin/requests/{c.id}", c.case_number or f"AMP-{c.id:04d}")
    for i in ideas:
        add_item(i.implementation_deadline, "💡", i.title, "Дедлайн ідеї / мініпроєкту", "idea", f"/admin/ideas/{i.id}", idea_status_label(i.status))
    for freeze, user in freezes:
        freeze_day = max(freeze.starts_at.date(), period_start)
        freeze_end_day = min(freeze.ends_at.date(), period_end)
        while freeze_day <= freeze_end_day:
            add_item(
                datetime.combine(freeze_day, datetime.min.time()), "❄️", f"{user.full_name} — заморозка серії", "Freeze",
                "freeze", f"/admin/streaks/{user.id}",
                f"{freeze.starts_at.strftime('%d.%m')}–{freeze.ends_at.strftime('%d.%m')} • {freeze.days} дн.",
            )
            freeze_day += timedelta(days=1)

    items.sort(key=lambda item: (item["when"], item["title"].lower()))
    by_day: dict[str, list[dict]] = {}
    for item in items:
        by_day.setdefault(item["when"].date().isoformat(), []).append(item)

    days = []
    cursor = period_start
    while cursor <= period_end:
        days.append({
            "date": cursor,
            "key": cursor.isoformat(),
            "entries": by_day.get(cursor.isoformat(), []),
            "current_month": cursor.month == selected.month,
            "today": cursor == date.today(),
        })
        cursor += timedelta(days=1)

    months_ua = ["", "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"]
    if view == "day":
        title = selected.strftime("%d.%m.%Y")
    elif view == "week":
        title = f"{period_start.strftime('%d.%m')} — {period_end.strftime('%d.%m.%Y')}"
    else:
        title = f"{months_ua[selected.month]} {selected.year}"

    return templates.TemplateResponse(
        request=request, name="calendar.html",
        context=ctx(
            request, items=items, days=days, by_day=by_day, view=view,
            selected=selected, period_start=period_start, period_end=period_end,
            prev_date=prev_date, next_date=next_date, title=title, today=date.today(),
        ),
    )


@router.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if r := guard(request):
        return r
    async with db.session_factory() as session:
        values = await get_runtime_values(session)
    grouped = {
        section: [spec for spec in RULE_SPECS if spec.section == section]
        for section in SECTIONS
    }
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=ctx(request, values=values, grouped=grouped, sections=SECTIONS),
    )


@router.post("/admin/settings")
async def settings_update(request: Request):
    if r := guard_permission(request, "settings.manage"):
        return r
    form = await request.form()
    payload = {}
    for spec in RULE_SPECS:
        field = spec.key.replace(".", "__")
        payload[spec.key] = form.get(field, spec.default)
    async with db.session_factory() as session:
        values = await set_runtime_values(session, payload)
        await log_audit(
            session,
            "web_runtime_settings_update",
            actor_label=request.session.get("admin_name", "superadmin"),
            entity_type="system",
            details="; ".join(f"{key}={value}" for key, value in sorted(values.items())),
        )
        await session.commit()
    return RedirectResponse("/admin/settings?saved=1", status_code=303)
