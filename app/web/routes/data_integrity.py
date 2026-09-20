from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update

from app.data_integrity import duplicate_match_reasons, scan_data_integrity, user_reference_summary
from app.domain_services import revoke_referral_reward_if_inactive
from app.model_domains import User, UserRole, UserStatus, UserStatusChangeRequest
from app.privacy_retention import cleanup_retained_data
from app.time_utils import clock
from app.web.dependencies import (
    ctx,
    db,
    guard_superadmin,
    log_audit,
    process_event_operations,
    queue_telegram_delivery,
    settings,
    templates,
)

router = APIRouter()


@router.get("/admin/data-integrity", response_class=HTMLResponse)
async def data_integrity_center(request: Request, notice: str = ""):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        report = await scan_data_integrity(session)
        await log_audit(
            session, "web_data_integrity_scan", actor_label=request.session.get("admin_name", "web"),
            entity_type="system", details=f"groups={report['issue_groups']}; affected={report['affected']}",
        )
        await session.commit()
    return templates.TemplateResponse(
        request=request,
        name="data_integrity.html",
        context=ctx(request, report=report, notice=notice),
    )


@router.post("/admin/data-integrity/retention-cleanup")
async def data_integrity_retention_cleanup(request: Request):
    if r := guard_superadmin(request):
        return r
    summary = await cleanup_retained_data(db, settings, actor_label=request.session.get("admin_name", "web"))
    return RedirectResponse(f"/admin/data-integrity?notice=retention:{summary.total}", status_code=303)


@router.post("/admin/data-integrity/refresh-event-operations")
async def data_integrity_refresh_events(request: Request):
    if r := guard_superadmin(request):
        return r
    async with db.session_factory() as session:
        changed = await process_event_operations(session)
        await log_audit(
            session, "web_data_integrity_event_refresh", actor_label=request.session.get("admin_name", "web"),
            entity_type="system", details=str(changed),
        )
        await session.commit()
    count = sum(int(v or 0) for v in changed.values())
    return RedirectResponse(f"/admin/data-integrity?notice=events:{count}", status_code=303)


@router.post("/admin/data-integrity/duplicate-delete")
async def data_integrity_duplicate_delete(
    request: Request,
    duplicate_user_id: int = Form(...),
    canonical_user_id: int = Form(...),
    confirmation: str = Form(...),
):
    """Remove a confirmed duplicate without silently destroying participation history.

    If the duplicate has no foreign-key references, the empty duplicate row is
    physically deleted. If history already references the profile, it is instead
    permanently archived so attendance/XP/audit history keeps referential integrity.
    """
    if r := guard_superadmin(request):
        return r
    if duplicate_user_id == canonical_user_id:
        raise HTTPException(status_code=400, detail="Основний профіль і дублікат не можуть бути одним записом.")
    if confirmation.strip().upper() != "ВИДАЛИТИ":
        raise HTTPException(status_code=400, detail="Для видалення введіть слово ВИДАЛИТИ.")

    actor = request.session.get("admin_name", "superadmin")
    async with db.session_factory() as session:
        duplicate = await session.scalar(select(User).where(User.id == duplicate_user_id).with_for_update())
        canonical = await session.scalar(select(User).where(User.id == canonical_user_id).with_for_update())
        if not duplicate or not canonical:
            raise HTTPException(status_code=404, detail="Один із профілів не знайдено.")
        if duplicate.permanent_deleted_at is not None:
            raise HTTPException(status_code=409, detail="Цей профіль уже видалений без можливості відновлення.")
        if canonical.permanent_deleted_at is not None:
            raise HTTPException(status_code=409, detail="Основний профіль уже позначений як остаточно видалений.")
        if duplicate.role not in {UserRole.PARTICIPANT.value, UserRole.AMBASSADOR.value}:
            raise HTTPException(status_code=409, detail="Профілі працівників/адміністраторів не можна видаляти через Data Integrity Center.")

        reasons = duplicate_match_reasons(duplicate, canonical)
        if not reasons:
            raise HTTPException(status_code=409, detail="Система більше не підтверджує, що ці профілі є дублями. Перескануйте Data Integrity Center.")

        references = await user_reference_summary(session, duplicate.id)
        ref_total = sum(int(item["count"]) for item in references)
        reason_text = ", ".join(reasons)
        now = clock.storage_utc()

        # Any pending status request becomes invalid after duplicate removal.
        await session.execute(
            update(UserStatusChangeRequest)
            .where(UserStatusChangeRequest.user_id == duplicate.id, UserStatusChangeRequest.status == "pending")
            .values(
                status="rejected",
                review_note="Профіль видалено як дублікат",
                reviewed_by_label=actor,
                reviewed_at=now,
            )
        )

        if ref_total == 0:
            deleted_name = duplicate.full_name
            await session.delete(duplicate)
            mode = "physical"
            audit_details = (
                f"duplicate_user={duplicate_user_id}; canonical_user={canonical_user_id}; "
                f"mode=physical; reasons={reason_text}; name={deleted_name}"
            )
        else:
            # Preserve all historical foreign keys. The profile is excluded from
            # active/default participant lists and from future duplicate scans.
            duplicate.status = UserStatus.DELETED_PERMANENT.value
            duplicate.permanent_deleted_at = now
            duplicate.deleted_at = duplicate.deleted_at or now
            duplicate.deletion_reason = (
                f"Видалено як дублікат профілю АМП-{canonical.id:04d}; збіг: {reason_text}"
            )
            duplicate.restoration_request_status = "closed"
            duplicate.restoration_requested_at = None
            duplicate.probation_started_at = None
            duplicate.probation_until = None
            mode = "archived"
            audit_details = (
                f"duplicate_user={duplicate.id}; canonical_user={canonical.id}; mode=archived; "
                f"reasons={reason_text}; fk_refs={ref_total}; "
                + "; ".join(f"{r['table']}.{r['column']}={r['count']}" for r in references[:20])
            )

            revoked = await revoke_referral_reward_if_inactive(
                session,
                duplicate,
                reason=f"Профіль видалено як дублікат АМП-{canonical.id:04d}",
            )
            if revoked:
                inviter, removed_xp, days_after = revoked
                await queue_telegram_delivery(
                    session,
                    inviter.tg_id,
                    "🤝 <b>Реферальний бонус скориговано</b>\n\n"
                    f"Профіль <b>{duplicate.full_name}</b> було підтверджено як дублікат іншого профілю. "
                    f"Скасовано <b>{removed_xp} XP</b> реферального бонусу.",
                    source="referral_clawback",
                    dedupe_key=f"referral_duplicate_clawback:{duplicate.id}",
                )

        await log_audit(
            session,
            "web_duplicate_user_removed",
            actor_label=actor,
            entity_type="user",
            entity_id=duplicate_user_id,
            details=audit_details,
        )
        await session.commit()

    notice = quote(f"duplicate:{mode}:{duplicate_user_id}:{canonical_user_id}", safe=":")
    return RedirectResponse(f"/admin/data-integrity?notice={notice}", status_code=303)
