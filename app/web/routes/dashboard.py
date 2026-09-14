from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.settlements import ensure_settlement_directory, settlement_quality_report
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        season = await current_season(session)
        stats = {
            "users": int(await session.scalar(select(func.count(User.id)).where(User.status == UserStatus.ACTIVE.value)) or 0),
            "ambassadors": int(await session.scalar(select(func.count(User.id)).where(User.status == UserStatus.ACTIVE.value, User.role.in_([UserRole.AMBASSADOR.value, UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value]))) or 0),
            "events": int(await session.scalar(select(func.count(Event.id))) or 0),
            "xp": int(await session.scalar(select(func.coalesce(func.sum(XPTransaction.amount), 0))) or 0),
            "rewards": int(await session.scalar(select(func.count(RewardClaim.id)).where(RewardClaim.status == "requested")) or 0),
            "tasks": int(await session.scalar(select(func.count(VolunteerTask.id)).where(VolunteerTask.status == "submitted")) or 0),
            "activities": int(await session.scalar(select(func.count(ActivityApplication.id)).where(ActivityApplication.status.in_(["activity_requested", "activity_submitted"]))) or 0),
            "requests": int(await session.scalar(select(func.count(RequestCase.id)).where(RequestCase.status.in_(["new", "in_review", "need_info"]))) or 0),
        }
        top = (await session.execute(
            select(User.id, User.full_name, func.coalesce(func.sum(XPTransaction.amount), 0).label("xp"))
            .join(XPTransaction, XPTransaction.user_id == User.id, isouter=True)
            .where(
                User.status == UserStatus.ACTIVE.value,
                or_(User.leaderboard_opt_in == True, User.leaderboard_opt_in.is_(None))
            )
            .group_by(User.id, User.full_name)
            .order_by(
                func.coalesce(func.sum(XPTransaction.amount), 0).desc(),
                User.full_name.asc()
            )
            .limit(10)
        )).all()
        recent = (await session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(4))).all() if is_superadmin(request) else []
        upcoming = (await session.scalars(
            select(Event).where(Event.status.in_(["open", "postponed"]), Event.starts_at >= datetime.now()).order_by(Event.starts_at.asc()).limit(5)
        )).all()
        now = datetime.utcnow()
        attention = []
        if has_web_permission(request, "participants.approve"):
            attention.extend([
                {
                    "count": int(await session.scalar(select(func.count(User.id)).where(User.status == UserStatus.PENDING.value)) or 0),
                    "icon": "👥", "title": "Нові учасники", "action": "Переглянути", "url": "/admin/users?status=pending",
                },
                {
                    "count": int(await session.scalar(select(func.count(User.id)).where(User.parental_consent_required == True, User.parental_consent_confirmed == False, User.status.in_([UserStatus.PENDING.value, UserStatus.ACTIVE.value]))) or 0),
                    "icon": "👪", "title": "Батьківські згоди очікуються", "action": "Переглянути", "url": "/admin/users?consent=pending",
                },
                {
                    "count": int(await session.scalar(select(func.count(User.id)).where(User.status == UserStatus.DELETED.value, User.restoration_request_status == "pending")) or 0),
                    "icon": "♻️", "title": "Запити на відновлення акаунтів", "action": "Розглянути", "url": "/admin/users?status=deleted",
                },
            ])
        if has_web_permission(request, "quests.manage"):
            attention.append({
                "count": int(await session.scalar(select(func.count(QuestParticipation.id)).where(QuestParticipation.status == "completed")) or 0),
                "icon": "🎯", "title": "Квести очікують перевірки", "action": "Перевірити", "url": "/admin/quests?review=completed",
            })
        if has_web_permission(request, "activities.manage"):
            attention.append({
                "count": int(await session.scalar(select(func.count(ActivityApplication.id)).where(ActivityApplication.status.in_(["activity_requested", "activity_submitted"]))) or 0),
                "icon": "⚡", "title": "Активності очікують підтвердження", "action": "Опрацювати", "url": "/admin/activities?status=attention",
            })
        if has_web_permission(request, "cases.manage"):
            attention.append({
                "count": int(await session.scalar(select(func.count(RequestCase.id)).where(RequestCase.response_deadline.is_not(None), RequestCase.response_deadline < now, RequestCase.status.not_in(["resolved", "case_closed"]))) or 0),
                "icon": "🆘", "title": "Прострочені звернення", "action": "Відкрити", "url": "/admin/requests?overdue=1",
            })
        if has_web_permission(request, "ideas.manage"):
            attention.append({
                "count": int(await session.scalar(select(func.count(Idea.id)).where(Idea.status == "new")) or 0),
                "icon": "💡", "title": "Нові ідеї", "action": "Розглянути", "url": "/admin/ideas?status=new",
            })
        if has_web_permission(request, "notifications.manage"):
            attention.append({
                "count": int(await session.scalar(select(func.count(Notification.id)).where(Notification.status == "failed")) or 0),
                "icon": "📨", "title": "Невдалі Telegram-повідомлення", "action": "Повторити", "url": "/admin/notifications?status=failed",
            })
        attention = [item for item in attention if item["count"] > 0]
        data_quality = await settlement_quality_report(session)
        return templates.TemplateResponse(
            request=request, name="dashboard.html",
            context=ctx(request, stats=stats, top=top, season=season, recent=recent, upcoming=upcoming, attention=attention, data_quality=data_quality)
        )


@router.post("/admin/data-quality/settlements/normalize")
async def normalize_settlements(request: Request):
    if r := guard_permission(request, "participants.edit"):
        return r
    async with db.session_factory() as session:
        changed = await ensure_settlement_directory(session)
        await log_audit(
            session, "web_settlement_data_quality_normalize",
            actor_label=request.session.get("admin_name", "web"), entity_type="system",
            details=f"Нормалізовано профілів: {changed}",
        )
        await session.commit()
    return RedirectResponse("/admin/dashboard#data-quality", 303)

