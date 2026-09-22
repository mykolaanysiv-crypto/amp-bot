from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
from app.web.dependencies import (
    ActivityApplication, AuditLog, Event, EventFeedback, EventRegistration, HTMLResponse, Idea, Notification, QuestParticipation, RedirectResponse, Request, RequestCase, RewardClaim, User, UserRole, UserStatus, VolunteerTask, XPTransaction, ctx, current_season, db, func, guard, guard_permission, has_web_permission, is_superadmin, log_audit, or_, select, sql_case, templates, timedelta
)
from app.settlements import ensure_settlement_directory, settlement_quality_report
from app.registration_ux import registration_funnel_counts
from app.runtime_config import get_runtime_int
from app.governance import scan_operational_issues, SEVERITY_ORDER
from app.model_domains import OperationalIssue
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
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
            .where(User.status == UserStatus.ACTIVE.value, or_(User.leaderboard_opt_in == True, User.leaderboard_opt_in.is_(None)))
            .group_by(User.id, User.full_name)
            .order_by(func.coalesce(func.sum(XPTransaction.amount), 0).desc(), User.full_name.asc())
            .limit(10)
        )).all()
        recent = (await session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(4))).all() if is_superadmin(request) else []

        event_now = clock.local_wall()
        utc_now = clock.storage_utc()
        day_start = event_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        upcoming = (await session.scalars(
            select(Event).where(Event.status.in_(["open", "postponed"]), Event.starts_at >= event_now).order_by(Event.starts_at.asc()).limit(5)
        )).all()
        today_events = list((await session.scalars(
            select(Event).where(Event.starts_at >= day_start, Event.starts_at < day_end).order_by(Event.starts_at.asc()).limit(10)
        )).all())
        today_event_ids = [row.id for row in today_events]
        today_no_show = 0
        today_attended = 0
        if today_event_ids:
            today_no_show = int(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.event_id.in_(today_event_ids), EventRegistration.status == "no_show")) or 0)
            today_attended = int(await session.scalar(select(func.count(EventRegistration.id)).where(EventRegistration.event_id.in_(today_event_ids), EventRegistration.status.in_(["checked_in", "attended"]))) or 0)

        checkin_before = await get_runtime_int(session, "events.checkin_open_before_minutes")
        checkin_horizon = event_now + timedelta(hours=24, minutes=checkin_before)
        upcoming_checkins = list((await session.scalars(
            select(Event).where(
                Event.status.in_(["open", "postponed"]),
                Event.starts_at >= event_now,
                Event.starts_at <= checkin_horizon,
            ).order_by(Event.starts_at.asc()).limit(8)
        )).all())

        pending_registrations = int(await session.scalar(
            select(func.count(User.id)).where(User.registration_review_status == "pending")
        ) or 0)
        failed_notifications = int(await session.scalar(
            select(func.count(Notification.id)).where(Notification.status == "failed")
        ) or 0)
        sla_overdue = int(await session.scalar(select(func.count(RequestCase.id)).where(
            RequestCase.response_deadline.is_not(None), RequestCase.response_deadline < utc_now,
            RequestCase.status.not_in(["resolved", "case_closed"]),
        )) or 0)
        sla_due_soon = int(await session.scalar(select(func.count(RequestCase.id)).where(
            RequestCase.response_deadline.is_not(None), RequestCase.response_deadline >= utc_now,
            RequestCase.response_deadline <= utc_now + timedelta(hours=24),
            RequestCase.status.not_in(["resolved", "case_closed"]),
        )) or 0)

        feedback_since = utc_now - timedelta(days=30)
        feedback_invited = int(await session.scalar(select(func.count(EventFeedback.id)).where(
            EventFeedback.prompted_at.is_not(None), EventFeedback.prompted_at >= feedback_since
        )) or 0)
        feedback_completed = int(await session.scalar(select(func.count(EventFeedback.id)).where(
            EventFeedback.prompted_at.is_not(None), EventFeedback.prompted_at >= feedback_since,
            EventFeedback.status == "completed",
        )) or 0)
        feedback_rate = round(feedback_completed * 100 / feedback_invited, 1) if feedback_invited else 0.0
        feedback_by_event_rows = (await session.execute(
            select(
                Event.id, Event.title,
                func.count(EventFeedback.id).label("invited"),
                func.sum(sql_case((EventFeedback.status == "completed", 1), else_=0)).label("completed"),
            )
            .join(EventFeedback, EventFeedback.event_id == Event.id)
            .where(EventFeedback.prompted_at.is_not(None), EventFeedback.prompted_at >= feedback_since)
            .group_by(Event.id, Event.title)
            .order_by(func.max(EventFeedback.prompted_at).desc())
            .limit(6)
        )).all()
        feedback_by_event = [
            {"id": eid, "title": title, "invited": int(invited or 0), "completed": int(completed or 0),
             "rate": round(int(completed or 0) * 100 / int(invited or 1), 1) if int(invited or 0) else 0.0}
            for eid, title, invited, completed in feedback_by_event_rows
        ]
        funnel = await registration_funnel_counts(session)
        funnel_order = ["start", "consent", "profile", "submit", "approved", "first_activity"]
        funnel_labels = {
            "start": "Почали", "consent": "Згода", "profile": "Профіль", "submit": "Надіслали",
            "approved": "Схвалено", "first_activity": "Перша активність",
        }
        registration_funnel = []
        previous = None
        for key in funnel_order:
            count = int(funnel.get(key, 0))
            step_rate = round(count * 100 / previous, 1) if previous else (100.0 if count else 0.0)
            total_rate = round(count * 100 / max(1, int(funnel.get("start", 0))), 1) if funnel.get("start") else 0.0
            registration_funnel.append({"key": key, "label": funnel_labels[key], "count": count, "step_rate": step_rate, "total_rate": total_rate})
            previous = count

        attention = []
        if has_web_permission(request, "participants.approve"):
            attention.extend([
                {"count": pending_registrations, "icon": "📝", "title": "Нові реєстрації", "action": "Перевірити", "url": "/admin/registrations"},
                {"count": int(await session.scalar(select(func.count(User.id)).where(User.parental_consent_required == True, User.parental_consent_confirmed == False, User.status.in_([UserStatus.PENDING.value, UserStatus.ACTIVE.value]))) or 0), "icon": "👪", "title": "Батьківські згоди очікуються", "action": "Переглянути", "url": "/admin/users?consent=pending"},
                {"count": int(await session.scalar(select(func.count(User.id)).where(User.status == UserStatus.DELETED.value, User.restoration_request_status == "pending")) or 0), "icon": "♻️", "title": "Запити на відновлення акаунтів", "action": "Розглянути", "url": "/admin/users?status=deleted"},
            ])
        if has_web_permission(request, "quests.manage"):
            attention.append({"count": int(await session.scalar(select(func.count(QuestParticipation.id)).where(QuestParticipation.status == "completed")) or 0), "icon": "🎯", "title": "Квести очікують перевірки", "action": "Перевірити", "url": "/admin/quests?review=completed"})
        if has_web_permission(request, "activities.manage"):
            attention.append({"count": int(await session.scalar(select(func.count(ActivityApplication.id)).where(ActivityApplication.status.in_(["activity_requested", "activity_submitted"]))) or 0), "icon": "⚡", "title": "Активності очікують підтвердження", "action": "Опрацювати", "url": "/admin/activities?status=attention"})
        if has_web_permission(request, "cases.manage"):
            attention.extend([
                {"count": sla_overdue, "icon": "🆘", "title": "Прострочені звернення", "action": "Відкрити", "url": "/admin/requests?overdue=1"},
                {"count": sla_due_soon, "icon": "⏱", "title": "SLA звернень спливає за 24 год", "action": "Перевірити", "url": "/admin/requests"},
            ])
        if has_web_permission(request, "ideas.manage"):
            attention.append({"count": int(await session.scalar(select(func.count(Idea.id)).where(Idea.status == "new")) or 0), "icon": "💡", "title": "Нові ідеї", "action": "Розглянути", "url": "/admin/ideas?status=new"})
        if has_web_permission(request, "notifications.manage"):
            attention.append({"count": failed_notifications, "icon": "📨", "title": "Невдалі Telegram-повідомлення", "action": "Повторити", "url": "/admin/notifications?status=failed"})
        attention = [item for item in attention if item["count"] > 0]
        if is_superadmin(request):
            await scan_operational_issues(session)
            await session.commit()
            operational_tasks = list((await session.scalars(
                select(OperationalIssue).where(OperationalIssue.status == "open").order_by(OperationalIssue.last_seen_at.desc()).limit(8)
            )).all())
            operational_tasks.sort(key=lambda row: (SEVERITY_ORDER.get(row.severity, 9), -row.last_seen_at.timestamp()))
        else:
            operational_tasks = []
        data_quality = await settlement_quality_report(session)
        operations = {
            "today_events": len(today_events), "today_attended": today_attended, "today_no_show": today_no_show,
            "upcoming_checkins": len(upcoming_checkins), "pending_registrations": pending_registrations,
            "failed_notifications": failed_notifications, "sla_overdue": sla_overdue, "sla_due_soon": sla_due_soon,
            "data_quality_issues": int(data_quality.get("duplicate_count", 0)) + int(data_quality.get("noncanonical_count", 0)),
        }
        return templates.TemplateResponse(
            request=request, name="dashboard.html",
            context=ctx(
                request, stats=stats, top=top, season=season, recent=recent, upcoming=upcoming,
                attention=attention, data_quality=data_quality, operations=operations,
                today_events=today_events, upcoming_checkins=upcoming_checkins,
                feedback_conversion={"invited": feedback_invited, "completed": feedback_completed, "rate": feedback_rate},
                feedback_by_event=feedback_by_event, registration_funnel=registration_funnel, operational_tasks=operational_tasks,
            )
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

