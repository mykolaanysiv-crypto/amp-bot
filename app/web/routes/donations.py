from __future__ import annotations

from app.time_utils import clock

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.donations import award_donation_badges, sync_monobank_donations
from app.models import DonationJarState, DonationReport, DonationTransaction, SupportPageView, User, UserStatus
from app.web.app import (
    ctx, db, delete_image, guard_permission, is_superadmin, log_audit, notify_telegram,
    save_document, settings, templates,
)

router = APIRouter()


def _uah_to_kop(value: str) -> int:
    raw = (value or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return 0
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail="Некоректна сума.") from exc
    if amount < 0:
        raise HTTPException(status_code=400, detail="Сума не може бути від’ємною.")
    return int(amount * 100)


def _money(kop: int | None) -> str:
    value = Decimal(int(kop or 0)) / Decimal(100)
    text = f"{value:,.2f}".replace(",", " ")
    if text.endswith(".00"):
        text = text[:-3]
    return f"{text} грн"


async def _page_context(request: Request, *, notice: str = ""):
    async with db.session_factory() as session:
        state = await session.get(DonationJarState, 1)
        all_txs = list((await session.scalars(
            select(DonationTransaction).order_by(DonationTransaction.occurred_at.desc())
        )).all())
        txs = all_txs[:500]
        reports = list((await session.scalars(
            select(DonationReport).order_by(DonationReport.spent_at.desc().nullslast(), DonationReport.created_at.desc())
        )).all())
        users = list((await session.scalars(
            select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name.asc())
        )).all())
        support_views = int(await session.scalar(select(func.count(SupportPageView.id))) or 0)
        unique_support_users = int(await session.scalar(
            select(func.count(func.distinct(SupportPageView.tg_id))).where(SupportPageView.tg_id.is_not(None))
        ) or 0)

        income = [row for row in all_txs if int(row.amount_kop or 0) > 0 and int(row.currency_code or 980) == 980]
        amounts = [int(row.amount_kop or 0) for row in income]
        total_collected = sum(amounts)
        largest = max(amounts, default=0)
        average = int(round(total_collected / len(amounts))) if amounts else 0
        donor_keys = {
            f"user:{row.linked_user_id}" if row.linked_user_id else f"name:{(row.counter_name or '').strip().lower()}"
            for row in income if row.linked_user_id or (row.counter_name or "").strip()
        }
        spent_total = sum(int(r.amount_spent_kop or 0) for r in reports if r.published)
        daily = defaultdict(int)
        for row in income:
            daily[row.occurred_at.date()] += int(row.amount_kop or 0)
        daily_rows = [{"date": day, "amount_kop": amount} for day, amount in sorted(daily.items())]
        daily_max = max((x["amount_kop"] for x in daily_rows), default=1)
        for row in daily_rows:
            row["pct"] = max(2.0, row["amount_kop"] / daily_max * 100) if row["amount_kop"] else 0

        balance = int(state.balance_kop or 0) if state else 0
        goal = int(state.goal_kop or 0) if state else 0
        progress = min(100.0, max(0.0, balance / goal * 100)) if goal > 0 else 0.0
        linked_count = sum(1 for row in income if row.linked_user_id)
        return ctx(
            request,
            jar_state=state,
            transactions=txs,
            reports=reports,
            active_users=users,
            jar_url=settings.donation_jar_url,
            monobank_enabled=bool(settings.monobank_token),
            total_collected=total_collected,
            largest_donation=largest,
            average_donation=average,
            donation_count=len(income),
            donor_count=len(donor_keys),
            linked_count=linked_count,
            support_views=support_views,
            unique_support_users=unique_support_users,
            spent_total=spent_total,
            daily_rows=daily_rows[-31:],
            jar_progress=progress,
            money=_money,
            notice=notice,
            show_sensitive_donation_data=is_superadmin(request),
        )


@router.get("/admin/donations", response_class=HTMLResponse)
async def donations_page(request: Request):
    if r := guard_permission(request, "donations.manage"):
        return r
    return templates.TemplateResponse(request=request, name="donations.html", context=await _page_context(request))


@router.post("/admin/donations/sync")
async def donations_sync(request: Request):
    if r := guard_permission(request, "donations.manage"):
        return r
    async with db.session_factory() as session:
        result = await sync_monobank_donations(session, settings)
        await log_audit(
            session, "web_donations_sync", actor_label=request.session.get("admin_name", "web"),
            entity_type="donations", details=f"ok={result.get('ok')}; imported={result.get('imported')}; linked={result.get('linked')}",
        )
        await session.commit()
        for user_id, badge_names in (result.get("awarded") or {}).items():
            user = await session.get(User, int(user_id))
            if user and user.tg_id:
                await notify_telegram(user.tg_id, "💙 <b>Дякуємо за підтримку АМП!</b>\n\n🏅 Нові бейджі: " + ", ".join(badge_names))
    notice = "Синхронізацію завершено." if result.get("ok") else f"Помилка синхронізації: {result.get('error') or 'невідома помилка'}"
    return templates.TemplateResponse(request=request, name="donations.html", context=await _page_context(request, notice=notice))


@router.post("/admin/donations/transactions/{transaction_id}/link")
async def donation_link_participant(request: Request, transaction_id: int, user_id: str = Form("")):
    if r := guard_permission(request, "donations.manage"):
        return r
    notify_tg = None
    badge_names: list[str] = []
    async with db.session_factory() as session:
        row = await session.get(DonationTransaction, transaction_id)
        if not row:
            raise HTTPException(status_code=404, detail="Транзакцію не знайдено.")
        previous = row.linked_user_id
        uid = int(user_id) if str(user_id).strip().isdigit() else None
        if uid and not await session.get(User, uid):
            raise HTTPException(status_code=404, detail="Учасника не знайдено.")
        row.linked_user_id = uid
        if uid and int(row.amount_kop or 0) > 0:
            badges = await award_donation_badges(session, uid)
            badge_names = [b.name for b in badges]
            user = await session.get(User, uid)
            notify_tg = user.tg_id if user else None
        await log_audit(
            session, "web_donation_transaction_link", actor_label=request.session.get("admin_name", "web"),
            entity_type="donation_transaction", entity_id=row.id, details=f"user {previous or '—'} -> {uid or '—'}",
        )
        await session.commit()
    if notify_tg and badge_names:
        await notify_telegram(notify_tg, "💙 <b>Донат пов’язано з вашим профілем АМП.</b>\n\n🏅 Нові бейджі: " + ", ".join(badge_names))
    return RedirectResponse("/admin/donations#transactions", 303)


@router.post("/admin/donations/reports/create")
async def donation_report_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    amount_spent: str = Form(""),
    spent_at: str = Form(""),
    published: str | None = Form(None),
    document: UploadFile | None = File(None),
):
    if r := guard_permission(request, "donations.manage"):
        return r
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Назва звіту є обов’язковою.")
    document_path = await save_document(document, "donation_reports") if document and document.filename else None
    spent_dt = None
    if spent_at:
        try:
            spent_dt = datetime.fromisoformat(spent_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некоректна дата використання коштів.") from exc
    async with db.session_factory() as session:
        row = DonationReport(
            title=title,
            description=description.strip(),
            amount_spent_kop=_uah_to_kop(amount_spent),
            spent_at=spent_dt,
            document_path=document_path,
            document_name=(document.filename[:255] if document and document.filename else None),
            published=bool(published),
            updated_at=clock.storage_utc(),
        )
        session.add(row)
        await session.flush()
        await log_audit(session, "web_donation_report_create", actor_label=request.session.get("admin_name", "web"), entity_type="donation_report", entity_id=row.id, details=row.title)
        await session.commit()
    return RedirectResponse("/admin/donations#reporting", 303)


@router.post("/admin/donations/reports/{report_id}/toggle")
async def donation_report_toggle(request: Request, report_id: int):
    if r := guard_permission(request, "donations.manage"):
        return r
    async with db.session_factory() as session:
        row = await session.get(DonationReport, report_id)
        if not row:
            raise HTTPException(status_code=404, detail="Звіт не знайдено.")
        row.published = not row.published
        row.updated_at = clock.storage_utc()
        await log_audit(session, "web_donation_report_publish", actor_label=request.session.get("admin_name", "web"), entity_type="donation_report", entity_id=row.id, details=f"published={row.published}")
        await session.commit()
    return RedirectResponse("/admin/donations#reporting", 303)


@router.post("/admin/donations/reports/{report_id}/delete")
async def donation_report_delete(request: Request, report_id: int):
    if r := guard_permission(request, "donations.manage"):
        return r
    document_path = None
    async with db.session_factory() as session:
        row = await session.get(DonationReport, report_id)
        if not row:
            raise HTTPException(status_code=404, detail="Звіт не знайдено.")
        document_path = row.document_path
        await log_audit(session, "web_donation_report_delete", actor_label=request.session.get("admin_name", "web"), entity_type="donation_report", entity_id=row.id, details=row.title)
        await session.delete(row)
        await session.commit()
    if document_path:
        await delete_image(document_path)
    return RedirectResponse("/admin/donations#reporting", 303)
