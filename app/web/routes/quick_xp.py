from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.model_domains import QuickXPChallenge, QuickXPCompletion, User, UserStatus
from app.quick_xp import QUICK_XP_KINDS, QUICK_XP_WEEKLY_CAP, dump_options, kind_label, parse_options
from app.reliability import queue_telegram_delivery
from app.time_utils import clock
from app.web.dependencies import ctx, db, guard, has_web_permission, log_audit, templates

router = APIRouter()


def _guard(request: Request):
    if r := guard(request):
        return r
    if not (has_web_permission(request, "activities.manage") or has_web_permission(request, "gamification.manage")):
        return HTMLResponse("<h1>403</h1><p>Потрібне право керування активностями або гейміфікацією.</p>", status_code=403)
    return None


def _parse_dt(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    try:
        local = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "Некоректна дата/час") from exc
    return clock.storage_utc(clock.local_wall_to_utc(local))


def _input_dt(value):
    if not value:
        return ""
    aware = clock.from_storage_utc(value)
    return clock.utc_to_local(aware).strftime("%Y-%m-%dT%H:%M") if aware else ""


def _options_from_text(raw: str | None) -> list[str]:
    return [line.strip() for line in (raw or "").splitlines() if line.strip()][:8]


@router.get("/admin/quick-xp", response_class=HTMLResponse)
async def quick_xp_page(request: Request, notice: str = ""):
    if r := _guard(request): return r
    async with db.session_factory() as session:
        rows = list((await session.scalars(select(QuickXPChallenge).order_by(QuickXPChallenge.active.desc(), QuickXPChallenge.created_at.desc()))).all())
        counts = dict((await session.execute(
            select(QuickXPCompletion.challenge_id, func.count(QuickXPCompletion.id)).group_by(QuickXPCompletion.challenge_id)
        )).all())
        awarded = dict((await session.execute(
            select(QuickXPCompletion.challenge_id, func.coalesce(func.sum(QuickXPCompletion.xp_awarded), 0)).group_by(QuickXPCompletion.challenge_id)
        )).all())
    return templates.TemplateResponse(
        request=request,
        name="quick_xp.html",
        context=ctx(
            request, rows=rows, counts=counts, awarded=awarded, notice=notice,
            kind_label=kind_label, parse_options=parse_options, input_dt=_input_dt,
            weekly_cap=QUICK_XP_WEEKLY_CAP,
        ),
    )


@router.post("/admin/quick-xp/create")
async def quick_xp_create(request: Request):
    if r := _guard(request): return r
    form = await request.form()
    title = str(form.get("title") or "").strip()
    kind = str(form.get("kind") or "quiz").strip()
    if len(title) < 3:
        raise HTTPException(400, "Вкажіть назву завдання")
    if kind not in QUICK_XP_KINDS:
        raise HTTPException(400, "Некоректний тип завдання")
    xp = max(1, min(5, int(form.get("xp_reward") or 3)))
    duration = max(1, min(15, int(form.get("duration_minutes") or 2)))
    options = _options_from_text(str(form.get("options") or ""))
    correct_raw = str(form.get("correct_option") or "").strip()
    correct = int(correct_raw) - 1 if correct_raw.isdigit() else None
    question = str(form.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "Додайте питання/підказку для учасника")
    if kind == "video" and not str(form.get("media_url") or "").strip():
        raise HTTPException(400, "Для відеозавдання додайте посилання на відео")
    if kind in {"quiz", "video"}:
        if len(options) < 2 or correct is None or correct < 0 or correct >= len(options):
            raise HTTPException(400, "Для квізу/відео додайте щонайменше 2 варіанти та номер правильної відповіді")
    if kind == "poll" and len(options) < 2:
        raise HTTPException(400, "Для мініопитування додайте щонайменше 2 варіанти")
    if kind == "comment" and not question:
        raise HTTPException(400, "Для короткої відповіді додайте питання")
    async with db.session_factory() as session:
        row = QuickXPChallenge(
            title=title[:180], kind=kind,
            description=str(form.get("description") or "").strip()[:4000],
            xp_reward=xp, duration_minutes=duration,
            question=question[:2000], options_json=dump_options(options), correct_option=correct,
            media_url=str(form.get("media_url") or "").strip()[:500],
            starts_at=_parse_dt(str(form.get("starts_at") or "")),
            ends_at=_parse_dt(str(form.get("ends_at") or "")),
            active=form.get("active") == "on",
            featured_home=form.get("featured_home") == "on",
            sort_order=max(0, min(9999, int(form.get("sort_order") or 100))),
            created_by_label=str(request.session.get("admin_name") or "web")[:160],
            created_at=clock.storage_utc(), updated_at=clock.storage_utc(),
        )
        session.add(row); await session.flush()
        await log_audit(session, "web_quick_xp_create", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_challenge", entity_id=row.id, details=f"{row.title}; {row.kind}; +{row.xp_reward} XP")
        await session.commit()
    return RedirectResponse("/admin/quick-xp?notice=created", 303)


@router.post("/admin/quick-xp/{challenge_id}/update")
async def quick_xp_update(request: Request, challenge_id: int):
    if r := _guard(request): return r
    form = await request.form()
    async with db.session_factory() as session:
        row = await session.get(QuickXPChallenge, challenge_id)
        if not row:
            raise HTTPException(404, "Завдання не знайдено")
        row.title = str(form.get("title") or row.title).strip()[:180] or row.title
        row.description = str(form.get("description") or "").strip()[:4000]
        row.xp_reward = max(1, min(5, int(form.get("xp_reward") or row.xp_reward or 3)))
        row.duration_minutes = max(1, min(15, int(form.get("duration_minutes") or row.duration_minutes or 2)))
        row.question = str(form.get("question") or row.question or "").strip()[:2000]
        if "options" in form:
            row.options_json = dump_options(_options_from_text(str(form.get("options") or "")))
        if "correct_option" in form:
            raw_correct = str(form.get("correct_option") or "").strip()
            row.correct_option = int(raw_correct) - 1 if raw_correct.isdigit() else None
        row.media_url = str(form.get("media_url") or row.media_url or "").strip()[:500]
        row.active = form.get("active") == "on"
        row.featured_home = form.get("featured_home") == "on"
        row.starts_at = _parse_dt(str(form.get("starts_at") or ""))
        row.ends_at = _parse_dt(str(form.get("ends_at") or ""))
        row.sort_order = max(0, min(9999, int(form.get("sort_order") or row.sort_order or 100)))
        row.updated_at = clock.storage_utc()
        await log_audit(session, "web_quick_xp_update", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_challenge", entity_id=row.id, details=f"{row.title}; active={row.active}; featured={row.featured_home}")
        await session.commit()
    return RedirectResponse("/admin/quick-xp?notice=updated", 303)


@router.post("/admin/quick-xp/{challenge_id}/broadcast")
async def quick_xp_broadcast(request: Request, challenge_id: int):
    if r := _guard(request): return r
    queued = 0
    async with db.session_factory() as session:
        row = await session.get(QuickXPChallenge, challenge_id)
        if not row or not row.active:
            raise HTTPException(400, "Спочатку активуйте завдання")
        completed_ids = select(QuickXPCompletion.user_id).where(QuickXPCompletion.challenge_id == row.id)
        users = list((await session.scalars(select(User).where(
            User.status == UserStatus.ACTIVE.value,
            User.tg_id.is_not(None),
            User.id.not_in(completed_ids),
        ))).all())
        stamp = clock.storage_utc().strftime("%Y%m%d%H")
        for user in users:
            notification = await queue_telegram_delivery(
                session, user.tg_id,
                f"⚡ <b>Є швидкі +{row.xp_reward} XP</b>\n\n<b>{row.title}</b>\n{row.description}\n\n⏱ ~{row.duration_minutes} хв\n🎁 +{row.xp_reward} XP",
                source="quick_xp", dedupe_key=f"quick_xp:{row.id}:{user.id}:{stamp}",
                recipient_user_id=user.id, entity_type="quick_xp_challenge", entity_id=row.id,
                button_text="⚡ Виконати зараз", callback_data=f"quickxp:{row.id}",
            )
            if notification:
                queued += 1
        await log_audit(session, "web_quick_xp_broadcast", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_challenge", entity_id=row.id, details=f"queued={queued}")
        await session.commit()
    return RedirectResponse(f"/admin/quick-xp?notice=broadcast:{queued}", 303)
