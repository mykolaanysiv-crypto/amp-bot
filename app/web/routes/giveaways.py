from __future__ import annotations

import json
from datetime import datetime
from html import escape

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.giveaways import (
    GIVEAWAY_AUDIENCE_TYPES,
    GIVEAWAY_PARTICIPATION_MODES,
    audience_label,
    approved_draw_user_ids,
    eligible_user_ids,
    participation_label,
    run_draw,
)
from app.model_domains import Event, Giveaway, GiveawayEntry, GiveawayPrize, GiveawayWinner, User, UserStatus
from app.reliability import queue_telegram_delivery
from app.time_utils import clock
from app.ui_labels import label
from app.web.dependencies import (
    ctx, db, delete_stored_image, guard, has_web_permission, log_audit, save_image, templates,
)

router = APIRouter()


def _guard(request: Request):
    if r := guard(request):
        return r
    if not has_web_permission(request, "gamification.manage"):
        return HTMLResponse("<h1>403</h1><p>Керування розіграшами потребує права «Гейміфікація».</p>", status_code=403)
    return None


def _parse_local_datetime(raw: str | None, *, required: bool = False, label_text: str = "дату") -> datetime | None:
    value = (raw or "").strip()
    if not value:
        if required:
            raise HTTPException(status_code=400, detail=f"Вкажіть {label_text}.")
        return None
    try:
        local_wall = datetime.fromisoformat(value)
        return clock.storage_utc(clock.local_wall_to_utc(local_wall))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некоректно вказано {label_text}.") from exc


def _display_local_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    aware = clock.from_storage_utc(value)
    return clock.utc_to_local(aware).strftime("%d.%m.%Y %H:%M") if aware else "—"


def _input_local_dt(value: datetime | None) -> str:
    if not value:
        return ""
    aware = clock.from_storage_utc(value)
    return clock.utc_to_local(aware).strftime("%Y-%m-%dT%H:%M") if aware else ""


def _draw_block_reason(
    giveaway: Giveaway,
    *,
    eligible_count: int,
    prize_unit_count: int,
    now: datetime | None = None,
) -> str:
    """Return a human-readable reason why a draw cannot run yet.

    This is intentionally shared by GET and POST so the admin never lands on a
    raw JSON HTTPException page for an expected business-rule validation.
    """
    if giveaway.status == "cancelled":
        return "Скасований розіграш не можна проводити."
    if giveaway.status == "drawn":
        return ""
    if giveaway.status == "draft":
        return "Розіграш ще у статусі «Чернетка». Спочатку активуйте його або закрийте вручну, якщо хочете провести розіграш одразу."
    current = now or clock.storage_utc()
    if giveaway.status == "active" and giveaway.ends_at and current < giveaway.ends_at:
        return f"Дедлайн ще не настав — { _display_local_dt(giveaway.ends_at) }. Щоб провести розіграш зараз, спочатку натисніть «⏹ Закрити» вище."
    if prize_unit_count < 1:
        return "У розіграші немає подарунків із доступною кількістю."
    if eligible_count < prize_unit_count:
        return f"Недостатньо допущених учасників: потрібно щонайменше {prize_unit_count}, зараз {eligible_count}."
    return ""


def _audience_from_form(form) -> tuple[str, str]:
    kind = str(form.get("audience_type") or "all").strip()
    if kind not in GIVEAWAY_AUDIENCE_TYPES:
        raise HTTPException(status_code=400, detail="Некоректна аудиторія розіграшу.")
    if kind in {"all", "team"}:
        return kind, ""
    if kind == "event":
        raw = str(form.get("audience_event_id") or "").strip()
        if not raw.isdigit():
            raise HTTPException(status_code=400, detail="Для аудиторії події оберіть подію.")
        return kind, raw
    if kind == "roles":
        roles = [str(v) for v in form.getlist("audience_roles") if str(v) in {"participant", "ambassador", "coordinator", "admin", "superadmin"}]
        if not roles:
            raise HTTPException(status_code=400, detail="Оберіть щонайменше одну роль.")
        return kind, json.dumps(sorted(set(roles)), ensure_ascii=False)
    ids = []
    for raw in form.getlist("audience_users"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        raise HTTPException(status_code=400, detail="Оберіть щонайменше одного учасника.")
    return kind, json.dumps(sorted(set(ids)))


async def _prize_payloads(request: Request, form) -> list[dict]:
    rows: list[dict] = []
    for idx in range(1, 6):
        title = str(form.get(f"prize_title_{idx}") or "").strip()
        if not title:
            continue
        try:
            quantity = int(form.get(f"prize_quantity_{idx}") or 1)
        except (TypeError, ValueError):
            quantity = 1
        if quantity < 1 or quantity > 100:
            raise HTTPException(status_code=400, detail="Кількість одного подарунка має бути від 1 до 100.")
        upload = form.get(f"prize_photo_{idx}")
        image_path = await save_image(upload if getattr(upload, "filename", None) else None, "giveaway_prizes")
        rows.append({
            "title": title[:180],
            "description": str(form.get(f"prize_description_{idx}") or "").strip()[:3000],
            "quantity": quantity,
            "image_path": image_path,
            "sort_order": idx,
        })
    if not rows:
        raise HTTPException(status_code=400, detail="Додайте щонайменше один подарунок.")
    return rows


@router.get("/admin/giveaways", response_class=HTMLResponse)
async def giveaways_page(request: Request):
    if r := _guard(request): return r
    async with db.session_factory() as session:
        rows = list((await session.scalars(select(Giveaway).order_by(Giveaway.created_at.desc()))).all())
        events = list((await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(100))).all())
        users = list((await session.scalars(
            select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name.asc())
        )).all())
        prize_counts = dict((await session.execute(
            select(GiveawayPrize.giveaway_id, func.sum(GiveawayPrize.quantity)).group_by(GiveawayPrize.giveaway_id)
        )).all())
        winner_counts = dict((await session.execute(
            select(GiveawayWinner.giveaway_id, func.count(GiveawayWinner.id)).group_by(GiveawayWinner.giveaway_id)
        )).all())
    return templates.TemplateResponse(
        request=request,
        name="giveaways.html",
        context=ctx(request, rows=rows, events=events, users=users, prize_counts=prize_counts, winner_counts=winner_counts,
                    audience_label=audience_label, participation_label=participation_label, role_label=label, display_dt=_display_local_dt),
    )


@router.post("/admin/giveaways/create")
async def giveaway_create(request: Request):
    if r := _guard(request): return r
    form = await request.form()
    title = str(form.get("title") or "").strip()
    if len(title) < 3:
        raise HTTPException(status_code=400, detail="Назва розіграшу занадто коротка.")
    mode = str(form.get("participation_mode") or "automatic").strip()
    if mode not in GIVEAWAY_PARTICIPATION_MODES:
        raise HTTPException(status_code=400, detail="Некоректний спосіб участі.")
    task_text = str(form.get("task_text") or "").strip()
    if mode == "task" and len(task_text) < 5:
        raise HTTPException(status_code=400, detail="Для розіграшу із завданням опишіть умову участі.")
    audience_type, audience_value = _audience_from_form(form)
    starts_at = _parse_local_datetime(str(form.get("starts_at") or ""), label_text="дату початку") or clock.storage_utc()
    ends_at = _parse_local_datetime(str(form.get("ends_at") or ""), required=True, label_text="дедлайн розіграшу")
    if ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="Дедлайн має бути пізніше початку розіграшу.")
    status = str(form.get("status") or "draft")
    if status not in {"draft", "active"}:
        status = "draft"
    prizes = await _prize_payloads(request, form)
    now = clock.storage_utc()
    async with db.session_factory() as session:
        giveaway = Giveaway(
            title=title[:180], description=str(form.get("description") or "").strip()[:8000],
            participation_mode=mode, task_text=task_text[:8000], audience_type=audience_type,
            audience_value=audience_value, starts_at=starts_at, ends_at=ends_at, status=status,
            created_by_label=str(request.session.get("admin_name") or "web")[:160], created_at=now, updated_at=now,
        )
        session.add(giveaway)
        await session.flush()
        for row in prizes:
            session.add(GiveawayPrize(giveaway_id=giveaway.id, created_at=now, **row))
        await log_audit(session, "web_giveaway_create", actor_label=request.session.get("admin_name", "web"),
                        entity_type="giveaway", entity_id=giveaway.id,
                        details=f"mode={mode}; audience={audience_type}; prizes={len(prizes)}; {giveaway.title}")
        await session.commit()
        giveaway_id = giveaway.id
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}", status_code=303)


@router.get("/admin/giveaways/{giveaway_id}", response_class=HTMLResponse)
async def giveaway_detail(request: Request, giveaway_id: int):
    if r := _guard(request): return r
    async with db.session_factory() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if not giveaway:
            raise HTTPException(status_code=404, detail="Розіграш не знайдено.")
        prizes = list((await session.scalars(
            select(GiveawayPrize).where(GiveawayPrize.giveaway_id == giveaway.id).order_by(GiveawayPrize.sort_order, GiveawayPrize.id)
        )).all())
        entry_rows = list((await session.execute(
            select(GiveawayEntry, User).join(User, User.id == GiveawayEntry.user_id)
            .where(GiveawayEntry.giveaway_id == giveaway.id).order_by(GiveawayEntry.created_at.desc())
        )).all())
        winner_rows = list((await session.execute(
            select(GiveawayWinner, User, GiveawayPrize)
            .join(User, User.id == GiveawayWinner.user_id)
            .join(GiveawayPrize, GiveawayPrize.id == GiveawayWinner.prize_id)
            .where(GiveawayWinner.giveaway_id == giveaway.id)
            .order_by(GiveawayWinner.draw_order.asc())
        )).all())
        eligible_ids = await eligible_user_ids(session, giveaway)
        eligible_users = list((await session.scalars(select(User).where(User.id.in_(eligible_ids)).order_by(User.full_name.asc()))).all()) if eligible_ids else []
        draw_ids = await approved_draw_user_ids(session, giveaway)
        prize_unit_count = sum(max(0, int(p.quantity or 0)) for p in prizes)
        draw_block_reason = _draw_block_reason(
            giveaway, eligible_count=len(draw_ids), prize_unit_count=prize_unit_count
        )
        events = list((await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(100))).all())
        users = list((await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name))).all())
    winners_by_prize: dict[int, list[tuple[GiveawayWinner, User]]] = {}
    for winner, user, prize in winner_rows:
        winners_by_prize.setdefault(prize.id, []).append((winner, user))
    selected_roles: list[str] = []
    selected_users: list[int] = []
    if giveaway.audience_type in {"roles", "users"}:
        try:
            parsed = json.loads(giveaway.audience_value or "[]")
            if isinstance(parsed, list):
                if giveaway.audience_type == "roles":
                    selected_roles = [str(v) for v in parsed]
                else:
                    selected_users = [int(v) for v in parsed if str(v).isdigit()]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return templates.TemplateResponse(
        request=request,
        name="giveaway_detail.html",
        context=ctx(request, giveaway=giveaway, prizes=prizes, entry_rows=entry_rows, winner_rows=winner_rows,
                    winners_by_prize=winners_by_prize, eligible_users=eligible_users, draw_eligible_count=len(draw_ids),
                    prize_unit_count=prize_unit_count, draw_block_reason=draw_block_reason, can_draw=not bool(draw_block_reason),
                    events=events, users=users, audience_label=audience_label, participation_label=participation_label,
                    role_label=label, selected_roles=selected_roles, selected_users=selected_users, display_dt=_display_local_dt, input_dt=_input_local_dt),
    )


@router.post("/admin/giveaways/{giveaway_id}/update")
async def giveaway_update(request: Request, giveaway_id: int):
    if r := _guard(request): return r
    form = await request.form()
    async with db.session_factory() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if not giveaway:
            raise HTTPException(status_code=404, detail="Розіграш не знайдено.")
        if giveaway.status == "drawn":
            raise HTTPException(status_code=409, detail="Проведений розіграш не можна редагувати.")
        title = str(form.get("title") or "").strip()
        if len(title) < 3:
            raise HTTPException(status_code=400, detail="Назва розіграшу занадто коротка.")
        mode = str(form.get("participation_mode") or "automatic")
        if mode not in GIVEAWAY_PARTICIPATION_MODES:
            raise HTTPException(status_code=400, detail="Некоректний спосіб участі.")
        task_text = str(form.get("task_text") or "").strip()
        if mode == "task" and len(task_text) < 5:
            raise HTTPException(status_code=400, detail="Опишіть завдання для участі.")
        audience_type, audience_value = _audience_from_form(form)
        starts_at = _parse_local_datetime(str(form.get("starts_at") or ""), label_text="дату початку") or giveaway.starts_at
        ends_at = _parse_local_datetime(str(form.get("ends_at") or ""), required=True, label_text="дедлайн")
        if starts_at and ends_at <= starts_at:
            raise HTTPException(status_code=400, detail="Дедлайн має бути пізніше початку.")
        giveaway.title = title[:180]
        giveaway.description = str(form.get("description") or "").strip()[:8000]
        giveaway.participation_mode = mode
        giveaway.task_text = task_text[:8000]
        giveaway.audience_type = audience_type
        giveaway.audience_value = audience_value
        giveaway.starts_at = starts_at
        giveaway.ends_at = ends_at
        giveaway.updated_at = clock.storage_utc()
        await log_audit(session, "web_giveaway_update", actor_label=request.session.get("admin_name", "web"), entity_type="giveaway", entity_id=giveaway.id, details=giveaway.title)
        await session.commit()
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}", status_code=303)


@router.post("/admin/giveaways/{giveaway_id}/status")
async def giveaway_status(request: Request, giveaway_id: int):
    if r := _guard(request): return r
    form = await request.form()
    action = str(form.get("action") or "")
    mapping = {"activate": "active", "close": "closed", "cancel": "cancelled"}
    if action not in mapping:
        raise HTTPException(status_code=400, detail="Некоректна дія.")
    async with db.session_factory() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if not giveaway:
            raise HTTPException(status_code=404, detail="Розіграш не знайдено.")
        if giveaway.status == "drawn":
            raise HTTPException(status_code=409, detail="Проведений розіграш уже зафіксовано.")
        giveaway.status = mapping[action]
        giveaway.updated_at = clock.storage_utc()
        await log_audit(session, f"web_giveaway_{action}", actor_label=request.session.get("admin_name", "web"), entity_type="giveaway", entity_id=giveaway.id, details=giveaway.title)
        await session.commit()
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}", status_code=303)


@router.post("/admin/giveaways/{giveaway_id}/prizes/add")
async def giveaway_prize_add(request: Request, giveaway_id: int):
    if r := _guard(request): return r
    form = await request.form()
    async with db.session_factory() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if not giveaway or giveaway.status == "drawn":
            raise HTTPException(status_code=409, detail="До цього розіграшу не можна додати подарунок.")
        count = int(await session.scalar(select(func.count(GiveawayPrize.id)).where(GiveawayPrize.giveaway_id == giveaway.id)) or 0)
        if count >= 5:
            raise HTTPException(status_code=409, detail="У одному розіграші можна налаштувати до 5 типів подарунків.")
        title = str(form.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Вкажіть назву подарунка.")
        try: quantity = int(form.get("quantity") or 1)
        except (TypeError, ValueError): quantity = 1
        if quantity < 1 or quantity > 100:
            raise HTTPException(status_code=400, detail="Кількість має бути від 1 до 100.")
        upload = form.get("photo")
        image_path = await save_image(upload if getattr(upload, "filename", None) else None, "giveaway_prizes")
        row = GiveawayPrize(giveaway_id=giveaway.id, title=title[:180], description=str(form.get("description") or "").strip()[:3000], quantity=quantity, image_path=image_path, sort_order=count + 1, created_at=clock.storage_utc())
        session.add(row)
        await log_audit(session, "web_giveaway_prize_add", actor_label=request.session.get("admin_name", "web"), entity_type="giveaway", entity_id=giveaway.id, details=f"{row.title}; qty={quantity}")
        await session.commit()
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}#prizes", status_code=303)


@router.post("/admin/giveaway-prizes/{prize_id}/update")
async def giveaway_prize_update(request: Request, prize_id: int):
    if r := _guard(request): return r
    form = await request.form()
    async with db.session_factory() as session:
        prize = await session.get(GiveawayPrize, prize_id)
        if not prize:
            raise HTTPException(status_code=404, detail="Подарунок не знайдено.")
        giveaway = await session.get(Giveaway, prize.giveaway_id)
        if giveaway and giveaway.status == "drawn":
            raise HTTPException(status_code=409, detail="Подарунки проведеного розіграшу не можна змінювати.")
        title = str(form.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Вкажіть назву подарунка.")
        try: quantity = int(form.get("quantity") or 1)
        except (TypeError, ValueError): quantity = 1
        if quantity < 1 or quantity > 100:
            raise HTTPException(status_code=400, detail="Кількість має бути від 1 до 100.")
        old_path = prize.image_path
        upload = form.get("photo")
        new_path = await save_image(upload if getattr(upload, "filename", None) else None, "giveaway_prizes")
        remove = str(form.get("remove_image") or "") == "1"
        prize.title = title[:180]
        prize.description = str(form.get("description") or "").strip()[:3000]
        prize.quantity = quantity
        if new_path:
            prize.image_path = new_path
        elif remove:
            prize.image_path = None
        await session.commit()
        giveaway_id = prize.giveaway_id
    if old_path and (new_path or remove):
        await delete_stored_image(db, old_path)
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}#prizes", status_code=303)


@router.post("/admin/giveaway-prizes/{prize_id}/delete")
async def giveaway_prize_delete(request: Request, prize_id: int):
    if r := _guard(request): return r
    async with db.session_factory() as session:
        prize = await session.get(GiveawayPrize, prize_id)
        if not prize:
            raise HTTPException(status_code=404, detail="Подарунок не знайдено.")
        giveaway = await session.get(Giveaway, prize.giveaway_id)
        if giveaway and giveaway.status == "drawn":
            raise HTTPException(status_code=409, detail="Подарунок уже є частиною зафіксованого результату.")
        count = int(await session.scalar(select(func.count(GiveawayPrize.id)).where(GiveawayPrize.giveaway_id == prize.giveaway_id)) or 0)
        if count <= 1:
            raise HTTPException(status_code=409, detail="У розіграші має залишатися щонайменше один подарунок.")
        giveaway_id, image_path = prize.giveaway_id, prize.image_path
        await session.delete(prize)
        await session.commit()
    if image_path:
        await delete_stored_image(db, image_path)
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}#prizes", status_code=303)


@router.post("/admin/giveaway-entries/{entry_id}/review")
async def giveaway_entry_review(request: Request, entry_id: int):
    if r := _guard(request): return r
    form = await request.form()
    action = str(form.get("action") or "")
    if action not in {"approve", "return", "reject"}:
        raise HTTPException(status_code=400, detail="Некоректна дія із заявкою.")
    async with db.session_factory() as session:
        entry = await session.get(GiveawayEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Заявку не знайдено.")
        giveaway = await session.get(Giveaway, entry.giveaway_id)
        user = await session.get(User, entry.user_id)
        if not giveaway or giveaway.status in {"drawn", "cancelled"}:
            raise HTTPException(status_code=409, detail="Розіграш уже не приймає зміни учасників.")
        note = str(form.get("review_note") or "").strip()[:3000]
        entry.status = {"approve": "approved", "return": "returned", "reject": "rejected"}[action]
        entry.review_note = note
        entry.reviewed_at = clock.storage_utc()
        entry.reviewed_by = str(request.session.get("admin_name") or "web")[:160]
        entry.updated_at = clock.storage_utc()
        if user and user.tg_id:
            text = {
                "approve": f"✅ <b>Участь у розіграші підтверджено</b>\n\n«{escape(giveaway.title)}»\nТи допущений/а до розіграшу.",
                "return": f"↩️ <b>Підтвердження потрібно доопрацювати</b>\n\n«{escape(giveaway.title)}»" + (f"\nКоментар: {escape(note)}" if note else ""),
                "reject": f"🚫 <b>Підтвердження не прийнято</b>\n\n«{escape(giveaway.title)}»" + (f"\nКоментар: {escape(note)}" if note else ""),
            }[action]
            await queue_telegram_delivery(session, user.tg_id, text, source="giveaway", dedupe_key=f"giveaway_entry_{action}:{entry.id}:{entry.updated_at.isoformat()}", recipient_user_id=user.id, entity_type="giveaway", entity_id=giveaway.id, button_text="🎲 Відкрити розіграш", callback_data=f"giveaway:{giveaway.id}")
        await log_audit(session, f"web_giveaway_entry_{action}", actor_label=request.session.get("admin_name", "web"), entity_type="giveaway_entry", entity_id=entry.id, details=f"giveaway={giveaway.id}; user={entry.user_id}; {note}")
        await session.commit()
        giveaway_id = giveaway.id
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}#participants", status_code=303)


@router.post("/admin/giveaways/{giveaway_id}/draw")
async def giveaway_draw(request: Request, giveaway_id: int):
    if r := _guard(request): return r
    form = await request.form()
    if str(form.get("confirm") or "") != "yes":
        return RedirectResponse(f"/admin/giveaways/{giveaway_id}?notice=draw_confirm#results", status_code=303)
    async with db.session_factory() as session:
        giveaway = await session.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
        if not giveaway:
            raise HTTPException(status_code=404, detail="Розіграш не знайдено.")
        if giveaway.status == "drawn":
            return RedirectResponse(f"/admin/giveaways/{giveaway.id}#results", status_code=303)

        draw_ids = await approved_draw_user_ids(session, giveaway)
        prize_unit_count = int(await session.scalar(
            select(func.coalesce(func.sum(GiveawayPrize.quantity), 0)).where(GiveawayPrize.giveaway_id == giveaway.id)
        ) or 0)
        now = clock.storage_utc()
        block_reason = _draw_block_reason(
            giveaway, eligible_count=len(draw_ids), prize_unit_count=prize_unit_count, now=now
        )
        if block_reason:
            return RedirectResponse(f"/admin/giveaways/{giveaway.id}?notice=draw_blocked#results", status_code=303)

        try:
            winners, seed = await run_draw(session, giveaway)
        except ValueError:
            # Expected draw validation should stay inside the admin UI, not leak
            # a raw JSON error response into the browser.
            return RedirectResponse(f"/admin/giveaways/{giveaway.id}?notice=draw_blocked#results", status_code=303)
        for winner in winners:
            user = await session.get(User, winner.user_id)
            prize = await session.get(GiveawayPrize, winner.prize_id)
            if user and user.tg_id and prize:
                await queue_telegram_delivery(
                    session, user.tg_id,
                    f"🎉 <b>Вітаємо! Ви перемогли в розіграші «{escape(giveaway.title)}»</b>\n\n🎁 Ваш подарунок: <b>{escape(prize.title)}</b>\n\nЗ вами зв’яжеться адміністратор АМП, щоб уточнити деталі отримання подарунка.",
                    source="giveaway_winner", dedupe_key=f"giveaway_winner:{giveaway.id}:{winner.user_id}", recipient_user_id=user.id,
                    entity_type="giveaway", entity_id=giveaway.id, button_text="🎲 Переглянути результат", callback_data=f"giveaway:{giveaway.id}",
                )
                winner.notified_at = now
        await log_audit(session, "web_giveaway_draw", actor_label=request.session.get("admin_name", "web"), entity_type="giveaway", entity_id=giveaway.id, details=f"winners={len(winners)}; algorithm={giveaway.draw_algorithm}; seed={seed}")
        await session.commit()
    return RedirectResponse(f"/admin/giveaways/{giveaway_id}?notice=draw_success#results", status_code=303)
