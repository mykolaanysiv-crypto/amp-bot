from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select

from app.model_domains import QuickXPChallenge, QuickXPCompletion, QuickXPQuestion, User, UserStatus
from app.quick_xp import (
    QUICK_XP_KINDS,
    challenge_reward,
    dump_options,
    kind_label,
    parse_options,
    quick_xp_weekly_cap,
    sync_quiz_reward,
)
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
    return [line.strip() for line in (raw or "").splitlines() if line.strip()][:12]


def _int(raw, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _single_payload(form, kind: str) -> tuple[str, list[str], int | None, int, str]:
    question = str(form.get("single_question") or "").strip()
    options = _options_from_text(str(form.get("single_options") or ""))
    raw_correct = str(form.get("single_correct_option") or "").strip()
    correct = int(raw_correct) - 1 if raw_correct.isdigit() else None
    xp = _int(form.get("xp_reward"), 3, 1, 20)
    media_url = str(form.get("media_url") or "").strip()[:500]

    if kind == "video":
        if not media_url:
            raise HTTPException(400, "Для відеозавдання додайте посилання на відео")
        if not question or len(options) < 2 or correct is None or not (0 <= correct < len(options)):
            raise HTTPException(400, "Для відео додайте контрольне питання, щонайменше 2 варіанти та правильну відповідь")
    elif kind == "poll":
        if not question or len(options) < 2:
            raise HTTPException(400, "Для мініопитування додайте питання та щонайменше 2 варіанти")
        correct = None
    elif kind == "comment":
        if not question:
            raise HTTPException(400, "Для короткої відповіді додайте питання")
        options, correct = [], None
    return question, options, correct, xp, media_url


def _quiz_payload(form) -> list[dict]:
    texts = [str(v).strip() for v in form.getlist("quiz_question_text")]
    options_raw = [str(v) for v in form.getlist("quiz_question_options")]
    correct_raw = [str(v).strip() for v in form.getlist("quiz_question_correct")]
    xp_raw = [str(v).strip() for v in form.getlist("quiz_question_xp")]
    length = max(len(texts), len(options_raw), len(correct_raw), len(xp_raw), 0)
    rows: list[dict] = []
    for i in range(length):
        text = texts[i] if i < len(texts) else ""
        if not text:
            continue
        options = _options_from_text(options_raw[i] if i < len(options_raw) else "")
        raw = correct_raw[i] if i < len(correct_raw) else ""
        correct = int(raw) - 1 if raw.isdigit() else None
        if len(options) < 2 or correct is None or not (0 <= correct < len(options)):
            raise HTTPException(400, f"Питання {len(rows)+1}: додайте щонайменше 2 варіанти та правильний номер")
        rows.append({
            "text": text[:2000],
            "options": options,
            "correct": correct,
            "xp": _int(xp_raw[i] if i < len(xp_raw) else 1, 1, 1, 20),
        })
    if not rows:
        raise HTTPException(400, "Для мініквізу додайте хоча б одне питання")
    return rows[:30]


@router.get("/admin/quick-xp", response_class=HTMLResponse)
async def quick_xp_page(request: Request, notice: str = ""):
    if r := _guard(request):
        return r
    async with db.session_factory() as session:
        rows = list((await session.scalars(
            select(QuickXPChallenge).order_by(QuickXPChallenge.active.desc(), QuickXPChallenge.created_at.desc())
        )).all())
        counts = dict((await session.execute(
            select(QuickXPCompletion.challenge_id, func.count(QuickXPCompletion.id)).group_by(QuickXPCompletion.challenge_id)
        )).all())
        awarded = dict((await session.execute(
            select(QuickXPCompletion.challenge_id, func.coalesce(func.sum(QuickXPCompletion.xp_awarded), 0)).group_by(QuickXPCompletion.challenge_id)
        )).all())
        questions = list((await session.scalars(
            select(QuickXPQuestion).order_by(QuickXPQuestion.challenge_id, QuickXPQuestion.sort_order, QuickXPQuestion.id)
        )).all())
        question_map: dict[int, list[QuickXPQuestion]] = {}
        for question in questions:
            question_map.setdefault(question.challenge_id, []).append(question)
        reward_map = {row.id: await challenge_reward(session, row) for row in rows}
        weekly_cap = await quick_xp_weekly_cap(session)
    return templates.TemplateResponse(
        request=request,
        name="quick_xp.html",
        context=ctx(
            request,
            rows=rows,
            counts=counts,
            awarded=awarded,
            notice=notice,
            kind_label=kind_label,
            parse_options=parse_options,
            input_dt=_input_dt,
            weekly_cap=weekly_cap,
            question_map=question_map,
            reward_map=reward_map,
        ),
    )


@router.post("/admin/quick-xp/create")
async def quick_xp_create(request: Request):
    if r := _guard(request):
        return r
    form = await request.form()
    title = str(form.get("title") or "").strip()
    kind = str(form.get("kind") or "quiz").strip()
    if len(title) < 3:
        raise HTTPException(400, "Вкажіть назву завдання")
    if kind not in QUICK_XP_KINDS:
        raise HTTPException(400, "Некоректний тип завдання")

    quiz_rows = _quiz_payload(form) if kind == "quiz" else []
    if kind == "quiz":
        question, options, correct, media_url = "", [], None, ""
        xp = sum(item["xp"] for item in quiz_rows)
    else:
        question, options, correct, xp, media_url = _single_payload(form, kind)

    async with db.session_factory() as session:
        row = QuickXPChallenge(
            title=title[:180],
            kind=kind,
            description=str(form.get("description") or "").strip()[:4000],
            xp_reward=xp,
            duration_minutes=_int(form.get("duration_minutes"), 2, 1, 30),
            question=question[:2000],
            options_json=dump_options(options),
            correct_option=correct,
            media_url=media_url,
            starts_at=_parse_dt(str(form.get("starts_at") or "")),
            ends_at=_parse_dt(str(form.get("ends_at") or "")),
            active=form.get("active") == "on",
            featured_home=form.get("featured_home") == "on",
            sort_order=100,
            created_by_label=str(request.session.get("admin_name") or "web")[:160],
            created_at=clock.storage_utc(),
            updated_at=clock.storage_utc(),
        )
        session.add(row)
        await session.flush()
        for idx, item in enumerate(quiz_rows, start=1):
            session.add(QuickXPQuestion(
                challenge_id=row.id,
                text=item["text"],
                options_json=dump_options(item["options"]),
                correct_option=item["correct"],
                xp_reward=item["xp"],
                sort_order=idx * 10,
                created_at=clock.storage_utc(),
            ))
        await log_audit(
            session,
            "web_quick_xp_create",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="quick_xp_challenge",
            entity_id=row.id,
            details=f"{row.title}; {row.kind}; max +{row.xp_reward} XP",
        )
        await session.commit()
    return RedirectResponse("/admin/quick-xp?notice=created", 303)


@router.post("/admin/quick-xp/{challenge_id}/update")
async def quick_xp_update(request: Request, challenge_id: int):
    if r := _guard(request):
        return r
    form = await request.form()
    kind = str(form.get("kind") or "quiz").strip()
    if kind not in QUICK_XP_KINDS:
        raise HTTPException(400, "Некоректний тип завдання")
    async with db.session_factory() as session:
        row = await session.get(QuickXPChallenge, challenge_id)
        if not row:
            raise HTTPException(404, "Завдання не знайдено")
        row.title = str(form.get("title") or row.title).strip()[:180] or row.title
        row.description = str(form.get("description") or "").strip()[:4000]
        row.duration_minutes = _int(form.get("duration_minutes"), row.duration_minutes or 2, 1, 30)
        row.kind = kind
        if kind == "quiz":
            row.question = ""
            row.options_json = "[]"
            row.correct_option = None
            row.media_url = ""
            q_count = int(await session.scalar(select(func.count(QuickXPQuestion.id)).where(QuickXPQuestion.challenge_id == row.id)) or 0)
            if q_count == 0:
                row.active = False
            else:
                row.active = form.get("active") == "on"
            await sync_quiz_reward(session, row.id)
        else:
            question, options, correct, xp, media_url = _single_payload(form, kind)
            row.question = question[:2000]
            row.options_json = dump_options(options)
            row.correct_option = correct
            row.xp_reward = xp
            row.media_url = media_url
            row.active = form.get("active") == "on"
        row.featured_home = form.get("featured_home") == "on"
        row.starts_at = _parse_dt(str(form.get("starts_at") or ""))
        row.ends_at = _parse_dt(str(form.get("ends_at") or ""))
        row.updated_at = clock.storage_utc()
        await log_audit(
            session,
            "web_quick_xp_update",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="quick_xp_challenge",
            entity_id=row.id,
            details=f"{row.title}; kind={row.kind}; active={row.active}; featured={row.featured_home}",
        )
        await session.commit()
    return RedirectResponse("/admin/quick-xp?notice=updated", 303)


@router.post("/admin/quick-xp/{challenge_id}/questions/create")
async def quick_xp_question_create(request: Request, challenge_id: int):
    if r := _guard(request):
        return r
    form = await request.form()
    text = str(form.get("text") or "").strip()
    options = _options_from_text(str(form.get("options") or ""))
    correct_raw = str(form.get("correct_option") or "").strip()
    correct = int(correct_raw) - 1 if correct_raw.isdigit() else None
    if not text or len(options) < 2 or correct is None or not (0 <= correct < len(options)):
        raise HTTPException(400, "Додайте текст питання, щонайменше 2 варіанти та правильний номер")
    xp = _int(form.get("xp_reward"), 1, 1, 20)
    async with db.session_factory() as session:
        challenge = await session.get(QuickXPChallenge, challenge_id)
        if not challenge:
            raise HTTPException(404, "Завдання не знайдено")
        if challenge.kind != "quiz":
            raise HTTPException(409, "Окремі питання доступні лише для мініквізу")
        max_order = int(await session.scalar(select(func.coalesce(func.max(QuickXPQuestion.sort_order), 0)).where(QuickXPQuestion.challenge_id == challenge_id)) or 0)
        question = QuickXPQuestion(
            challenge_id=challenge_id,
            text=text[:2000],
            options_json=dump_options(options),
            correct_option=correct,
            xp_reward=xp,
            sort_order=max_order + 10,
            created_at=clock.storage_utc(),
        )
        session.add(question)
        await session.flush()
        await sync_quiz_reward(session, challenge_id)
        await log_audit(session, "web_quick_xp_question_create", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_question", entity_id=question.id, details=f"challenge={challenge_id}; +{xp} XP")
        await session.commit()
    return RedirectResponse(f"/admin/quick-xp?notice=question-created#quick-xp-{challenge_id}", 303)


@router.post("/admin/quick-xp/{challenge_id}/questions/{question_id}/update")
async def quick_xp_question_update(request: Request, challenge_id: int, question_id: int):
    if r := _guard(request):
        return r
    form = await request.form()
    text = str(form.get("text") or "").strip()
    options = _options_from_text(str(form.get("options") or ""))
    correct_raw = str(form.get("correct_option") or "").strip()
    correct = int(correct_raw) - 1 if correct_raw.isdigit() else None
    if not text or len(options) < 2 or correct is None or not (0 <= correct < len(options)):
        raise HTTPException(400, "Перевірте текст, варіанти й номер правильної відповіді")
    async with db.session_factory() as session:
        question = await session.get(QuickXPQuestion, question_id)
        if not question or question.challenge_id != challenge_id:
            raise HTTPException(404, "Питання не знайдено")
        question.text = text[:2000]
        question.options_json = dump_options(options)
        question.correct_option = correct
        question.xp_reward = _int(form.get("xp_reward"), question.xp_reward or 1, 1, 20)
        await sync_quiz_reward(session, challenge_id)
        await log_audit(session, "web_quick_xp_question_update", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_question", entity_id=question.id, details=f"challenge={challenge_id}; +{question.xp_reward} XP")
        await session.commit()
    return RedirectResponse(f"/admin/quick-xp?notice=question-updated#quick-xp-{challenge_id}", 303)


@router.post("/admin/quick-xp/{challenge_id}/questions/{question_id}/move")
async def quick_xp_question_move(request: Request, challenge_id: int, question_id: int):
    if r := _guard(request):
        return r
    form = await request.form()
    direction = str(form.get("direction") or "")
    if direction not in {"up", "down"}:
        raise HTTPException(400, "Некоректний напрямок")
    async with db.session_factory() as session:
        rows = list((await session.scalars(select(QuickXPQuestion).where(QuickXPQuestion.challenge_id == challenge_id).order_by(QuickXPQuestion.sort_order, QuickXPQuestion.id))).all())
        index = next((i for i, item in enumerate(rows) if item.id == question_id), None)
        if index is None:
            raise HTTPException(404, "Питання не знайдено")
        other_index = index - 1 if direction == "up" else index + 1
        if 0 <= other_index < len(rows):
            rows[index].sort_order, rows[other_index].sort_order = rows[other_index].sort_order, rows[index].sort_order
            await session.commit()
    return RedirectResponse(f"/admin/quick-xp#quick-xp-{challenge_id}", 303)


@router.post("/admin/quick-xp/{challenge_id}/questions/{question_id}/delete")
async def quick_xp_question_delete(request: Request, challenge_id: int, question_id: int):
    if r := _guard(request):
        return r
    async with db.session_factory() as session:
        question = await session.get(QuickXPQuestion, question_id)
        if not question or question.challenge_id != challenge_id:
            raise HTTPException(404, "Питання не знайдено")
        await session.delete(question)
        await session.flush()
        await sync_quiz_reward(session, challenge_id)
        remaining = int(await session.scalar(select(func.count(QuickXPQuestion.id)).where(QuickXPQuestion.challenge_id == challenge_id)) or 0)
        challenge = await session.get(QuickXPChallenge, challenge_id)
        if challenge and remaining == 0:
            challenge.active = False
        await log_audit(session, "web_quick_xp_question_delete", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_question", entity_id=question_id, details=f"challenge={challenge_id}")
        await session.commit()
    return RedirectResponse(f"/admin/quick-xp?notice=question-deleted#quick-xp-{challenge_id}", 303)


@router.post("/admin/quick-xp/{challenge_id}/broadcast")
async def quick_xp_broadcast(request: Request, challenge_id: int):
    if r := _guard(request):
        return r
    queued = 0
    async with db.session_factory() as session:
        row = await session.get(QuickXPChallenge, challenge_id)
        if not row or not row.active:
            raise HTTPException(400, "Спочатку активуйте завдання")
        reward = await challenge_reward(session, row)
        completed_ids = select(QuickXPCompletion.user_id).where(QuickXPCompletion.challenge_id == row.id)
        users = list((await session.scalars(select(User).where(
            User.status == UserStatus.ACTIVE.value,
            User.tg_id.is_not(None),
            User.id.not_in(completed_ids),
        ))).all())
        stamp = clock.storage_utc().strftime("%Y%m%d%H")
        for user in users:
            notification = await queue_telegram_delivery(
                session,
                user.tg_id,
                f"⚡ <b>Є швидкі XP</b>\n\n<b>{row.title}</b>\n{row.description}\n\n⏱ ~{row.duration_minutes} хв\n🎁 До <b>+{reward} XP</b>",
                source="quick_xp",
                dedupe_key=f"quick_xp:{row.id}:{user.id}:{stamp}",
                recipient_user_id=user.id,
                entity_type="quick_xp_challenge",
                entity_id=row.id,
                button_text="⚡ Виконати зараз",
                callback_data=f"quickxp:{row.id}",
            )
            if notification:
                queued += 1
        await log_audit(session, "web_quick_xp_broadcast", actor_label=request.session.get("admin_name", "web"), entity_type="quick_xp_challenge", entity_id=row.id, details=f"queued={queued}")
        await session.commit()
    return RedirectResponse(f"/admin/quick-xp?notice=broadcast:{queued}", 303)
