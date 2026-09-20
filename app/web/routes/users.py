from __future__ import annotations

from app.time_utils import clock

import json
from datetime import datetime as dt_datetime, time as dt_time, timedelta as dt_timedelta

from fastapi import APIRouter
from sqlalchemy.orm import selectinload
from app.domain_services import revoke_referral_reward_if_inactive
from app.profile_data import split_display_name
from app.season_history import user_season_history
from app.web.dependencies import (
    ActivityApplication, Badge, BanRecord, ConsentHistory, EventRegistration, File, Form, GENDER_OPTIONS, HTMLResponse, HTTPException, Idea, MEDIA_CONSENT_VERSION, MediaAsset, Path, QuestParticipation, RedirectResponse, Referral, Request, Response, SurveyResponse, UploadFile, User, UserBadge, UserRole, UserStatus, UserStatusChangeRequest, VULNERABILITY_OPTIONS, VolunteerTaskParticipation, XPTransaction, add_active_users_to_default_team, add_xp, age_on, ctx, current_season, datetime, db, delete_stored_image, dump_vulnerabilities, func, gender_label, get_level, guard, guard_permission, guard_superadmin, has_web_permission, html_escape, is_superadmin, label, league_for_xp, load_vulnerabilities, log_audit, mask_email, mask_phone, media_consent_label, normalize_manual_xp, notify_telegram, or_, process_expired_bans, queue_telegram_delivery, refresh_user_streak, reward_referral_if_ready, save_document, season_xp, select, settings, templates, timedelta, update, vulnerability_labels, xp_total
)
from app.settlements import resolve_canonical_settlement
from app.registration_ux import mark_registration_approved
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/users", response_class=HTMLResponse)
async def users(request: Request, q: str = "", role: str = "", status: str = "", period: str = "", sort: str = "newest", consent: str = ""):
    if r := guard(request): return r
    async with db.session_factory() as session:
        # The participant base contains reviewed community members only. New or
        # rejected applications live on the dedicated Registrations work screen.
        stmt = select(User).where(User.registration_review_status == "approved")
        if q:
            like = f"%{q}%"
            searchable = [User.full_name.ilike(like), User.username.ilike(like), User.settlement.ilike(like)]
            raw = q.upper().replace("AMP-", "").replace("АМП-", "")
            if raw.isdigit(): searchable.append(User.id == int(raw))
            if is_superadmin(request): searchable.extend([User.email.ilike(like), User.phone.ilike(like)])
            stmt = stmt.where(or_(*searchable))
        if role: stmt = stmt.where(User.role == role)
        if status:
            stmt = stmt.where(User.status == status)
        else:
            # Permanently deleted/duplicate-archived profiles remain available
            # through the explicit status filter, but do not clutter the default list.
            stmt = stmt.where(User.permanent_deleted_at.is_(None))
        if consent == "pending": stmt = stmt.where(User.parental_consent_required == True, User.parental_consent_confirmed == False)
        cutoff_map = {"7d": 7, "30d": 30, "90d": 90}
        if period in cutoff_map: stmt = stmt.where(User.created_at >= clock.storage_utc() - timedelta(days=cutoff_map[period]))
        order_map = {
            "oldest": User.created_at.asc(), "name": User.full_name.asc(),
            "inactive": User.last_activity_at.asc().nullsfirst(), "newest": User.created_at.desc(),
        }
        stmt = stmt.order_by(order_map.get(sort, User.created_at.desc()))
        rows = (await session.scalars(stmt.limit(300))).all()
        season = await current_season(session)
        data = [(u, await xp_total(session,u.id), await season_xp(session,u.id,season.id if season else None)) for u in rows]
        pending_status_requests = []
        if has_web_permission(request, "participants.approve"):
            pending_status_requests = list((await session.execute(
                select(UserStatusChangeRequest, User).join(User, User.id == UserStatusChangeRequest.user_id)
                .where(UserStatusChangeRequest.status == "pending").order_by(UserStatusChangeRequest.created_at.asc()).limit(50)
            )).all())
        return templates.TemplateResponse(request=request, name="users.html", context=ctx(
            request, rows=data, q=q, role=role, status=status, period=period, sort=sort, consent=consent,
            pending_status_requests=pending_status_requests,
        ))


@router.get("/admin/registrations", response_class=HTMLResponse)
async def registrations_page(request: Request):
    if r := guard_permission(request, "participants.approve"):
        return r
    today = clock.today_local()
    local_start = dt_datetime.combine(today, dt_time.min)
    local_end = local_start + dt_timedelta(days=1)
    # Database timestamps are stored as naive UTC datetimes. Convert the local
    # calendar day through the canonical Clock so DST/midnight stay consistent.
    day_start, day_end = clock.local_period_to_storage_utc(local_start, local_end)
    async with db.session_factory() as session:
        pending = list((await session.scalars(
            select(User).where(User.registration_review_status == "pending").order_by(User.created_at.asc())
        )).all())
        approved_today = int(await session.scalar(
            select(func.count(User.id)).where(
                User.registration_review_status == "approved",
                User.registration_reviewed_at >= day_start,
                User.registration_reviewed_at < day_end,
            )
        ) or 0)
        rejected_count = int(await session.scalar(
            select(func.count(User.id)).where(User.registration_review_status == "rejected")
        ) or 0)
        rejected_recent = list((await session.scalars(
            select(User).where(User.registration_review_status == "rejected").order_by(User.registration_reviewed_at.desc().nullslast()).limit(50)
        )).all())
        rows = []
        for user in pending:
            rows.append({
                "user": user,
                "age": age_on(user.birth_date) if user.birth_date else None,
            })
    return templates.TemplateResponse(
        request=request, name="registrations.html",
        context=ctx(request, rows=rows, pending_count=len(rows), approved_today=approved_today, rejected_count=rejected_count, rejected_recent=rejected_recent),
    )


@router.post("/admin/registrations/{user_id}/reject")
async def registration_reject(request: Request, user_id: int, reason: str = Form(...)):
    if r := guard_permission(request, "participants.approve"):
        return r
    reason = reason.strip()
    if len(reason) < 5:
        raise HTTPException(status_code=400, detail="Вкажіть причину відхилення щонайменше з 5 символів.")
    notify_tg = None
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Заявку не знайдено.")
        user.registration_review_status = "rejected"
        user.registration_reviewed_at = clock.storage_utc()
        user.registration_reviewed_by = request.session.get("admin_name", "web")
        user.registration_rejection_reason = reason
        if user.status == UserStatus.PENDING.value:
            user.status = UserStatus.INACTIVE.value
        notify_tg = user.tg_id
        await log_audit(
            session, "web_user_registration_rejected", actor_label=request.session.get("admin_name", "web"),
            entity_type="user", entity_id=user.id, details=reason,
        )
        await session.commit()
    if notify_tg:
        await notify_telegram(
            notify_tg,
            "❌ <b>Реєстрацію в АМП поки не підтверджено.</b>\n\n"
            f"Причина: {html_escape(reason)}\n\nЯкщо вважаєте, що сталася помилка, зверніться до команди АМП.",
        )
    return RedirectResponse("/admin/registrations", 303)


@router.get("/admin/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int):
    if r := guard(request): return r
    sensitive = is_superadmin(request)
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user: return HTMLResponse("Не знайдено", status_code=404)
        total = await xp_total(session,user.id); sxp = await season_xp(session,user.id)
        streak_row, _ = await refresh_user_streak(session, user)
        league = league_for_xp(sxp)
        txs = (await session.scalars(select(XPTransaction).where(XPTransaction.user_id==user.id).order_by(XPTransaction.created_at.desc()).limit(50))).all()
        badges = (await session.execute(select(Badge).join(UserBadge,UserBadge.badge_id==Badge.id).where(UserBadge.user_id==user.id))).scalars().all()
        referrals = (await session.scalars(select(Referral).where(Referral.inviter_user_id==user.id).order_by(Referral.created_at.desc()))).all()
        consent_history = (await session.scalars(
            select(ConsentHistory).where(ConsentHistory.user_id==user.id).order_by(ConsentHistory.changed_at.desc()).limit(100)
        )).all() if sensitive else []
        pending_status_request = await session.scalar(
            select(UserStatusChangeRequest).where(
                UserStatusChangeRequest.user_id==user.id,
                UserStatusChangeRequest.status=="pending",
            ).order_by(UserStatusChangeRequest.created_at.desc())
        )
        first_name, last_name = split_display_name(user.full_name, user.first_name, user.last_name)
        vulnerabilities = vulnerability_labels(user.vulnerability_categories) if sensitive else []
        vulnerability_codes, vulnerability_other = load_vulnerabilities(user.vulnerability_categories) if sensitive else ([], "")
        await log_audit(
            session,
            "web_user_profile_view_sensitive" if sensitive else "web_user_profile_view_basic",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="user",
            entity_id=user.id,
            details="Переглянуто повну картку учасника" if sensitive else "Переглянуто базову картку учасника з прихованими чутливими даними",
        )
        season_history360 = await user_season_history(session, user.id)
        # Participant 360: one-page operational history across modules.
        event_regs = list((await session.scalars(select(EventRegistration).options(selectinload(EventRegistration.event)).where(EventRegistration.user_id==user.id).order_by(EventRegistration.registered_at.desc()))).all())
        quest_rows = list((await session.scalars(select(QuestParticipation).options(selectinload(QuestParticipation.quest)).where(QuestParticipation.user_id==user.id).order_by(QuestParticipation.joined_at.desc()))).all())
        task_rows = list((await session.scalars(select(VolunteerTaskParticipation).options(selectinload(VolunteerTaskParticipation.task)).where(VolunteerTaskParticipation.user_id==user.id).order_by(VolunteerTaskParticipation.joined_at.desc()))).all())
        activity_rows = list((await session.scalars(select(ActivityApplication).options(selectinload(ActivityApplication.activity_type)).where(ActivityApplication.user_id==user.id).order_by(ActivityApplication.requested_at.desc()))).all())
        idea_rows = list((await session.scalars(select(Idea).where(Idea.user_id==user.id).order_by(Idea.created_at.desc()))).all())
        survey_rows = list((await session.scalars(select(SurveyResponse).options(selectinload(SurveyResponse.survey)).where(SurveyResponse.user_id==user.id).order_by(SurveyResponse.completed_at.desc()))).all())
        kpi360 = {
            "events": sum(1 for r in event_regs if r.status=="attended"),
            "quests": sum(1 for r in quest_rows if r.status=="approved"),
            "tasks": sum(1 for r in task_rows if r.status=="approved"),
            "activities": sum(1 for r in activity_rows if r.status=="activity_completed"),
            "surveys": len(survey_rows), "ideas": len(idea_rows), "badges": len(badges),
            "referrals": sum(1 for r in referrals if r.status=="rewarded"),
        }
        timeline=[]
        for tx in txs:
            timeline.append({"at":tx.created_at,"icon":"⚡","title":f"{int(tx.amount):+d} XP — {label(tx.category)}","detail":tx.description or ""})
        for r in event_regs:
            if r.status=="attended":
                timeline.append({"at":r.confirmed_at or r.checkin_at or r.registered_at,"icon":"📅","title":"Відвідав/ла подію","detail":r.event.title if r.event else f"Подія #{r.event_id}"})
        for row in quest_rows:
            if row.status == "approved": timeline.append({"at":row.approved_at or row.completed_at or row.joined_at,"icon":"🎯","title":"Виконано квест","detail":row.quest.title if row.quest else f"Квест #{row.quest_id}"})
        for row in task_rows:
            if row.status == "approved": timeline.append({"at":row.approved_at or row.submitted_at or row.joined_at,"icon":"✅","title":"Виконано волонтерську задачу","detail":row.task.title if row.task else f"Задача #{row.task_id}"})
        for row in activity_rows:
            if row.status == "activity_completed": timeline.append({"at":row.completed_at or row.submitted_at or row.requested_at,"icon":"⚡","title":"Підтверджено активність","detail":row.activity_type.title if row.activity_type else f"Активність #{row.activity_type_id}"})
        for row in idea_rows: timeline.append({"at":row.created_at,"icon":"💡","title":"Подано ідею","detail":row.title})
        for row in survey_rows: timeline.append({"at":row.completed_at,"icon":"📋","title":"Пройдено опитування","detail":row.survey.title if row.survey else f"Опитування #{row.survey_id}"})
        badge_rows = list((await session.scalars(select(UserBadge).where(UserBadge.user_id==user.id).order_by(UserBadge.awarded_at.desc()))).all())
        for ub in badge_rows:
            badge=await session.get(Badge,ub.badge_id)
            timeline.append({"at":ub.awarded_at,"icon":"🏅","title":"Отримано бейдж","detail":badge.name if badge else f"Бейдж #{ub.badge_id}"})
        timeline=sorted([x for x in timeline if x.get("at")],key=lambda x:x["at"],reverse=True)[:100]
        try: restoration_answers=json.loads(user.restoration_answers_json or "{}")
        except Exception: restoration_answers={}
        await session.commit()
        return templates.TemplateResponse(
            request=request, name="user_detail.html",
            context=ctx(
                request, user=user, total=total, sxp=sxp, level=get_level(total)[0], txs=txs, badges=badges, referrals=referrals, league=league, streak_row=streak_row,
                kpi360=kpi360, timeline360=timeline, event_regs360=event_regs, quest_rows360=quest_rows, task_rows360=task_rows, activity_rows360=activity_rows, idea_rows360=idea_rows, survey_rows360=survey_rows, season_history360=season_history360, restoration_answers=restoration_answers,
                last_name=last_name, first_name=first_name, age=age_on(user.birth_date) if user.birth_date else None, vulnerabilities=vulnerabilities,
                vulnerability_options=VULNERABILITY_OPTIONS, vulnerability_codes=vulnerability_codes, vulnerability_other=vulnerability_other,
                gender_options=GENDER_OPTIONS, gender_text=gender_label(user.gender) if sensitive else "Приховано", media_consent_text=media_consent_label(user.media_consent),
                sensitive=sensitive, masked_phone=mask_phone(user.phone), masked_email=mask_email(user.email), consent_history=consent_history, pending_status_request=pending_status_request,
            )
        )


@router.post("/admin/users/{user_id}/basic-profile")
async def user_basic_profile_update(request: Request, user_id: int):
    """Edit only non-sensitive operational profile fields with participants.edit."""
    if r := guard_permission(request, "participants.edit"):
        return r
    form = await request.form()
    first_name = str(form.get("first_name") or "").strip()
    last_name = str(form.get("last_name") or "").strip()
    settlement = str(form.get("settlement") or "").strip() or None
    username = str(form.get("username") or "").strip().lstrip("@") or None
    if not first_name or not last_name:
        raise HTTPException(status_code=400, detail="Ім’я та прізвище є обов’язковими.")
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Учасника не знайдено")
        before = f"name={user.full_name}; settlement={user.settlement}; username={user.username}"
        user.first_name = first_name
        user.last_name = last_name
        user.full_name = f"{last_name} {first_name}".strip()
        user.settlement = await resolve_canonical_settlement(session, settlement)
        user.username = username
        await log_audit(
            session, "web_user_basic_profile_update", actor_label=request.session.get("admin_name", "web"),
            entity_type="user", entity_id=user.id,
            details=f"{before} -> name={user.full_name}; settlement={user.settlement}; username={user.username}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}", 303)


@router.post("/admin/users/{user_id}/profile")
async def user_profile_update(request: Request, user_id: int):
    """Update participant profile fields from the web admin panel.

    This route exists primarily for legacy users who completed registration
    before newer profile questions were introduced.
    """
    if r := guard_superadmin(request):
        return r
    form = await request.form()
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return HTMLResponse("Учасника не знайдено", status_code=404)

        first_name = str(form.get("first_name") or "").strip()
        last_name = str(form.get("last_name") or "").strip()
        email = str(form.get("email") or "").strip() or None
        phone = str(form.get("phone") or "").strip() or None
        settlement = str(form.get("settlement") or "").strip() or None
        username = str(form.get("username") or "").strip().lstrip("@") or None
        birth_raw = str(form.get("birth_date") or "").strip()
        gender = str(form.get("gender") or "").strip() or None
        if gender not in {code for code, _ in GENDER_OPTIONS}:
            gender = None
        media_raw = form.get("media_consent")
        media_consent = user.media_consent if media_raw is None else (True if str(media_raw).strip().lower() == "yes" else False if str(media_raw).strip().lower() == "no" else None)

        if not first_name or not last_name:
            raise HTTPException(status_code=400, detail="Ім’я та прізвище є обов’язковими.")

        birth_date = None
        if birth_raw:
            try:
                birth_date = datetime.strptime(birth_raw, "%Y-%m-%d").date()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Некоректна дата народження.") from exc
            if birth_date > clock.today_local():
                raise HTTPException(status_code=400, detail="Дата народження не може бути в майбутньому.")

        allowed_codes = {code for _, code, _ in VULNERABILITY_OPTIONS}
        vulnerability_codes = [str(code) for code in form.getlist("vulnerability") if str(code) in allowed_codes]
        if "no_category" in vulnerability_codes and len(set(vulnerability_codes)) > 1:
            raise HTTPException(status_code=400, detail="«Не відношусь до жодної категорії» не можна поєднувати з іншими статусами.")
        other_text = str(form.get("vulnerability_other") or "").strip()
        if other_text and "other" not in vulnerability_codes:
            vulnerability_codes.append("other")
        if "other" not in vulnerability_codes:
            other_text = ""

        old_media_consent = user.media_consent
        old_media_status = user.media_consent_status
        user.first_name = first_name
        user.last_name = last_name
        user.full_name = f"{last_name} {first_name}".strip()
        user.email = email
        user.phone = phone
        user.settlement = await resolve_canonical_settlement(session, settlement)
        user.username = username
        user.birth_date = birth_date
        user.gender = gender
        user.vulnerability_categories = dump_vulnerabilities(vulnerability_codes, other_text)
        user.media_consent = media_consent
        new_media_status = "granted" if media_consent is True else "declined" if media_consent is False else "pending"
        if new_media_status != old_media_status or media_consent != old_media_consent:
            user.media_consent_status = new_media_status
            user.media_consent_version = MEDIA_CONSENT_VERSION
            user.media_consent_recorded_at = clock.storage_utc()
            session.add(ConsentHistory(
                user_id=user.id, consent_type="media", status=new_media_status,
                version=user.media_consent_version, changed_by_label=request.session.get("admin_name","web"),
                changed_at=user.media_consent_recorded_at, note="Змінено під час редагування картки учасника",
            ))
        if birth_date:
            user.parental_consent_required = age_on(birth_date) < 18
            if not user.parental_consent_required and user.parental_consent_status == "pending":
                user.parental_consent_status = "not_required"

        await log_audit(
            session,
            "web_user_profile_update",
            actor_label=request.session.get("admin_name", "web"),
            entity_type="user",
            entity_id=user.id,
            details="Оновлено персональні дані картки учасника",
        )
        await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.post("/admin/users/{user_id}/consents")
async def user_consents_update(
    request: Request, user_id: int,
    parental_status: str=Form("not_required"), parental_received_at: str=Form(""),
    parental_file: UploadFile | None=File(None), remove_parental_file: str|None=Form(None),
    media_status: str=Form("pending"), media_version: str=Form(""), media_recorded_at: str=Form(""),
    note: str=Form(""),
):
    if r := guard_superadmin(request): return r
    if parental_status not in {"not_required","pending","received","revoked"}:
        raise HTTPException(status_code=400,detail="Некоректний статус згоди батьків")
    if media_status not in {"pending","granted","declined","revoked"}:
        raise HTTPException(status_code=400,detail="Некоректний статус фото/відеозгоди")
    def parse_optional(raw: str) -> datetime | None:
        raw=(raw or "").strip()
        if not raw: return None
        try: return datetime.fromisoformat(raw)
        except ValueError as exc: raise HTTPException(status_code=400,detail="Некоректна дата/час згоди") from exc
    received_at_input=parse_optional(parental_received_at)
    media_at_input=parse_optional(media_recorded_at)
    new_file=await save_document(parental_file,"consents")
    old_file_to_delete=None
    async with db.session_factory() as session:
        user=await session.get(User,user_id)
        if not user: raise HTTPException(status_code=404,detail="Учасника не знайдено")
        actor=request.session.get("admin_name","web")
        old_parental=(user.parental_consent_status,user.parental_consent_received_at,user.parental_consent_file_path)
        old_media=(user.media_consent_status,user.media_consent_version,user.media_consent_recorded_at)

        if new_file:
            old_file_to_delete=user.parental_consent_file_path
            user.parental_consent_file_path=new_file
        elif remove_parental_file:
            old_file_to_delete=user.parental_consent_file_path
            user.parental_consent_file_path=None
        user.parental_consent_status=parental_status
        user.parental_consent_confirmed=parental_status=="received"
        if parental_status=="received":
            user.parental_consent_received_at = received_at_input or (old_parental[1] if old_parental[0]=="received" else None) or clock.storage_utc()
        else:
            user.parental_consent_received_at = received_at_input
        # The field remains a demographic rule, not an admin switch.
        user.parental_consent_required=bool(user.birth_date and age_on(user.birth_date)<18)
        if (user.parental_consent_status,user.parental_consent_received_at,user.parental_consent_file_path) != old_parental:
            session.add(ConsentHistory(
                user_id=user.id,consent_type="parental",status=parental_status,file_path=user.parental_consent_file_path,
                note=note.strip(),changed_by_label=actor,changed_at=clock.storage_utc(),
            ))

        user.media_consent_status=media_status
        user.media_consent=True if media_status=="granted" else False if media_status in {"declined","revoked"} else None
        user.media_consent_version=(media_version or user.media_consent_version or MEDIA_CONSENT_VERSION).strip()
        media_core_changed=(user.media_consent_status,user.media_consent_version) != (old_media[0],old_media[1])
        user.media_consent_recorded_at = media_at_input or (clock.storage_utc() if media_core_changed else old_media[2])
        if (user.media_consent_status,user.media_consent_version,user.media_consent_recorded_at) != old_media:
            session.add(ConsentHistory(
                user_id=user.id,consent_type="media",status=media_status,version=user.media_consent_version,
                note=note.strip(),changed_by_label=actor,changed_at=user.media_consent_recorded_at or clock.storage_utc(),
            ))
        await log_audit(session,"web_user_consents_update",actor_label=actor,entity_type="user",entity_id=user.id,details=f"parental={parental_status}; media={media_status}; version={user.media_consent_version}")
        await session.commit()
    if old_file_to_delete and old_file_to_delete != new_file:
        await delete_stored_image(db,old_file_to_delete)
    return RedirectResponse(f"/admin/users/{user_id}#consents",303)


@router.get("/admin/users/{user_id}/consent-file")
async def user_consent_file(request: Request, user_id: int, download: int = 0):
    if r := guard_superadmin(request): return r
    async with db.session_factory() as session:
        user=await session.get(User,user_id)
        if not user or not user.parental_consent_file_path:
            raise HTTPException(status_code=404,detail="Документ не знайдено")
        path=user.parental_consent_file_path
        if path.startswith("/media/"):
            try: asset_id=int(path.rstrip("/").split("/")[-1])
            except ValueError as exc: raise HTTPException(status_code=404,detail="Документ не знайдено") from exc
            asset=await session.get(MediaAsset,asset_id)
            if not asset: raise HTTPException(status_code=404,detail="Документ не знайдено")
            await log_audit(
                session, "web_sensitive_document_download" if download else "web_sensitive_document_view",
                actor_label=request.session.get("admin_name","web"), entity_type="user", entity_id=user.id,
                details=f"parental_consent; media_asset={asset.id}",
            )
            await session.commit()
            disposition = "attachment" if download else "inline"
            return Response(content=asset.data,media_type=asset.content_type or "application/octet-stream",headers={"Cache-Control":"private, no-store","Content-Disposition":f'{disposition}; filename="{asset.filename or "consent"}"'})
    # Local development fallback. Resolve only inside AMP data/uploads.
    safe=(Path(settings.data_dir)/path.lstrip("/")).resolve()
    allowed_roots=[(Path(settings.data_dir)/"private"/"consents").resolve(), (Path(settings.data_dir)/"uploads"/"consents").resolve()]
    if not any(root == safe.parent or root in safe.parents for root in allowed_roots) or not safe.exists():
        raise HTTPException(status_code=404,detail="Документ не знайдено")
    suffix=safe.suffix.lower(); content_type={".pdf":"application/pdf",".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp"}.get(suffix,"application/octet-stream")
    async with db.session_factory() as session:
        await log_audit(
            session, "web_sensitive_document_download" if download else "web_sensitive_document_view",
            actor_label=request.session.get("admin_name","web"), entity_type="user", entity_id=user_id,
            details=f"parental_consent; local={safe.name}",
        )
        await session.commit()
    disposition = "attachment" if download else "inline"
    return Response(content=safe.read_bytes(),media_type=content_type,headers={"Cache-Control":"private, no-store","Content-Disposition":f'{disposition}; filename="{safe.name}"'})


@router.post("/admin/users/{user_id}/xp")
async def user_add_xp(request: Request, user_id: int, amount: int = Form(...), description: str = Form(...), category: str = Form("web_admin")):
    if r := guard(request): return r
    async with db.session_factory() as session:
        user=await session.get(User,user_id)
        if user:
            amount = normalize_manual_xp(amount)
            await add_xp(session,user,amount,description,category=category)
            await log_audit(session,"web_add_xp",actor_label=request.session.get("admin_name","web"),entity_type="user",entity_id=user.id,details=f"{amount} XP: {description}")
            await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}",303)


@router.post("/admin/users/{user_id}/activate")
async def user_activate_from_web(request: Request, user_id: int, return_to: str = Form("")):
    """Confirm a new participant directly from the web panel.

    Superadmins activate immediately. Regular admins create the same protected
    status-change request used elsewhere, so the approval chain stays intact.
    """
    if r := guard(request): return r
    notify_tg = None
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Учасника не знайдено")
        if user.status == UserStatus.BLOCKED.value:
            raise HTTPException(status_code=409, detail="Заблокований профіль активується лише через модерацію")
        if user.status in {UserStatus.DELETED.value, UserStatus.DELETED_PERMANENT.value}:
            raise HTTPException(status_code=409, detail="Видалений профіль не можна активувати вручну. Використайте workflow відновлення.")
        if user.status == UserStatus.ACTIVE.value:
            if user.registration_review_status != "approved":
                user.registration_review_status = "approved"
                user.registration_reviewed_at = clock.storage_utc()
                user.registration_reviewed_by = request.session.get("admin_name", "web")
                await mark_registration_approved(session, user.id)
                await session.commit()
            return RedirectResponse("/admin/registrations" if return_to == "registrations" else f"/admin/users/{user_id}", 303)
        actor = request.session.get("admin_name", "web")
        if has_web_permission(request, "participants.approve"):
            previous = user.status
            user.status = UserStatus.ACTIVE.value
            user.registration_review_status = "approved"
            user.registration_reviewed_at = clock.storage_utc()
            user.registration_reviewed_by = actor
            user.registration_rejection_reason = None
            await add_active_users_to_default_team(session)
            await reward_referral_if_ready(session, user, settings)
            await mark_registration_approved(session, user.id)
            notify_tg = user.tg_id
            await log_audit(session, "web_user_registration_approved", actor_label=actor, entity_type="user", entity_id=user.id, details=f"{previous}->active")
        else:
            await session.execute(
                update(UserStatusChangeRequest)
                .where(UserStatusChangeRequest.user_id == user.id, UserStatusChangeRequest.status == "pending")
                .values(status="rejected", review_note="Замінено запитом активації", reviewed_by_label="system", reviewed_at=clock.storage_utc())
            )
            session.add(UserStatusChangeRequest(
                user_id=user.id, previous_status=user.status, requested_status=UserStatus.ACTIVE.value,
                requested_by_label=actor, status="pending"
            ))
            await log_audit(session, "web_user_registration_activation_request", actor_label=actor, entity_type="user", entity_id=user.id, details="Запит активації нового учасника")
        await session.commit()
    if notify_tg:
        await notify_telegram(notify_tg, "✅ <b>Ваш профіль АМП підтверджено</b>\n\nРеєстрацію завершено. Відкрийте /start або головне меню, щоб користуватися всіма можливостями АМПасадорів.")
    return RedirectResponse("/admin/registrations" if return_to == "registrations" else f"/admin/users/{user_id}", 303)


@router.post("/admin/users/{user_id}/update")
async def user_update(request: Request, user_id: int, role: str = Form(...), status: str = Form(...)):
    if r := guard(request): return r
    allowed_statuses={UserStatus.PENDING.value,UserStatus.ACTIVE.value,UserStatus.INACTIVE.value}
    async with db.session_factory() as session:
        user=await session.get(User,user_id)
        if user:
            actor=request.session.get("admin_name","web")
            if user.status in {UserStatus.DELETED.value, UserStatus.DELETED_PERMANENT.value} and (role != user.role or status != user.status):
                raise HTTPException(status_code=409, detail="Статуси «Видалено» керуються тільки автоматично та через workflow відновлення.")
            was_active=user.status==UserStatus.ACTIVE.value
            old_role=user.role
            if is_superadmin(request) and role in {x.value for x in UserRole}:
                user.role=role
                if user.role != old_role:
                    # Role changes deliberately reset custom staff permissions.
                    # This prevents a permission set granted to a stronger role from
                    # silently surviving a later demotion. Superadmin can assign a
                    # new custom set immediately from Security → Access rights.
                    user.staff_permissions_json = None
                    await log_audit(session,"web_user_role_change",actor_label=actor,entity_type="user",entity_id=user.id,details=f"{old_role}->{user.role}; permissions=role_defaults")
            if status in allowed_statuses and user.status != UserStatus.BLOCKED.value and status != user.status:
                if is_superadmin(request):
                    user.status=status
                    if status == UserStatus.INACTIVE.value:
                        revoked = await revoke_referral_reward_if_inactive(
                            session, user, reason=f"Статус змінено на неактивний у web ({actor})"
                        )
                        if revoked:
                            inviter, removed_xp, days_after = revoked
                            await queue_telegram_delivery(
                                session, inviter.tg_id,
                                f"🤝 <b>Реферальний бонус скориговано</b>\n\n"
                                f"Ваш запрошений учасник <b>{user.full_name}</b> став неактивним через {days_after} дн. після активації. "
                                f"Оскільки це сталося протягом 30 днів, скасовано <b>{removed_xp} XP</b> реферального бонусу, отриманих за це запрошення.",
                                source="referral_clawback", dedupe_key=f"referral_clawback:{user.id}",
                            )
                else:
                    # Ordinary admins request the change; only a superadmin confirms it.
                    await session.execute(
                        update(UserStatusChangeRequest)
                        .where(UserStatusChangeRequest.user_id==user.id,UserStatusChangeRequest.status=="pending")
                        .values(status="rejected",review_note="Замінено новішим запитом",reviewed_by_label="system",reviewed_at=clock.storage_utc())
                    )
                    session.add(UserStatusChangeRequest(
                        user_id=user.id,previous_status=user.status,requested_status=status,requested_by_label=actor,status="pending"
                    ))
            if user.status==UserStatus.ACTIVE.value:
                await add_active_users_to_default_team(session)
                if not was_active: await reward_referral_if_ready(session,user,settings)
            await log_audit(session,"web_user_update",actor_label=actor,entity_type="user",entity_id=user.id,details=f"role={user.role}; current_status={user.status}; requested_status={status}")
            await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}",303)


def _safe_user_return_to(value: str, user_id: int) -> str:
    target = (value or "").strip()
    if target.startswith("/admin/") and not target.startswith("//"):
        return target
    return f"/admin/users/{user_id}"


@router.post("/admin/users/{user_id}/status-direct")
async def user_status_direct_change(
    request: Request,
    user_id: int,
    status: str = Form(...),
    return_to: str = Form(""),
):
    """Superadmin-only immediate participant lifecycle change.

    The route intentionally supports only pending/active/inactive. Blocked is
    managed by Moderation and deleted states by their dedicated workflows.
    """
    if r := guard_superadmin(request):
        return r
    allowed = {UserStatus.PENDING.value, UserStatus.ACTIVE.value, UserStatus.INACTIVE.value}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Дозволені статуси: очікує, активний, неактивний.")

    actor = request.session.get("admin_name", "superadmin")
    async with db.session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
        if not user:
            raise HTTPException(status_code=404, detail="Учасника не знайдено")
        if user.status == UserStatus.BLOCKED.value:
            raise HTTPException(status_code=409, detail="Заблокований профіль змінюється лише через модуль «Модерація».")
        if user.status in {UserStatus.DELETED.value, UserStatus.DELETED_PERMANENT.value}:
            raise HTTPException(status_code=409, detail="Видалений профіль змінюється лише через workflow відновлення.")

        previous = user.status
        if previous != status:
            was_active = previous == UserStatus.ACTIVE.value
            user.status = status
            await session.execute(
                update(UserStatusChangeRequest)
                .where(UserStatusChangeRequest.user_id == user.id, UserStatusChangeRequest.status == "pending")
                .values(
                    status="rejected",
                    review_note="Суперадміністратор змінив статус напряму",
                    reviewed_by_label=actor,
                    reviewed_at=clock.storage_utc(),
                )
            )

            if status == UserStatus.INACTIVE.value:
                revoked = await revoke_referral_reward_if_inactive(
                    session, user, reason=f"Суперадміністратор змінив статус на неактивний ({actor})"
                )
                if revoked:
                    inviter, removed_xp, days_after = revoked
                    await queue_telegram_delivery(
                        session, inviter.tg_id,
                        f"🤝 <b>Реферальний бонус скориговано</b>\n\n"
                        f"Запрошений учасник <b>{user.full_name}</b> став неактивним через {days_after} дн. після активації. "
                        f"Скасовано <b>{removed_xp} XP</b> реферального бонусу.",
                        source="referral_clawback", dedupe_key=f"referral_clawback:{user.id}",
                    )
            elif status == UserStatus.ACTIVE.value:
                user.registration_review_status = "approved"
                user.registration_reviewed_at = clock.storage_utc()
                user.registration_reviewed_by = actor
                user.registration_rejection_reason = None
                await mark_registration_approved(session, user.id)
                await add_active_users_to_default_team(session)
                if not was_active:
                    await reward_referral_if_ready(session, user, settings)

            await log_audit(
                session, "web_user_status_direct_change", actor_label=actor, entity_type="user", entity_id=user.id,
                details=f"{previous}->{status}",
            )
            await session.commit()

    return RedirectResponse(_safe_user_return_to(return_to, user_id), 303)


@router.post("/admin/users/{user_id}/status-request/{request_id}/approve")
async def user_status_request_approve(request: Request,user_id:int,request_id:int):
    if r := guard_permission(request, "participants.approve"): return r
    async with db.session_factory() as session:
        item=await session.get(UserStatusChangeRequest,request_id); user=await session.get(User,user_id)
        if not item or not user or item.user_id!=user.id or item.status!="pending": raise HTTPException(404,"Запит не знайдено")
        if user.status==UserStatus.BLOCKED.value: raise HTTPException(409,"Заблокований профіль змінюється лише через модерацію")
        if user.status in {UserStatus.DELETED.value, UserStatus.DELETED_PERMANENT.value}: raise HTTPException(409,"Видалений профіль змінюється лише через workflow відновлення")
        was_active=user.status==UserStatus.ACTIVE.value
        user.status=item.requested_status; item.status="approved"; item.reviewed_by_label=request.session.get("admin_name","superadmin"); item.reviewed_at=clock.storage_utc()
        if user.status == UserStatus.INACTIVE.value:
            revoked = await revoke_referral_reward_if_inactive(
                session, user, reason=f"Підтверджено запит на неактивний статус ({item.reviewed_by_label})"
            )
            if revoked:
                inviter, removed_xp, days_after = revoked
                await queue_telegram_delivery(
                    session, inviter.tg_id,
                    f"🤝 <b>Реферальний бонус скориговано</b>\n\n"
                    f"Ваш запрошений учасник <b>{user.full_name}</b> став неактивним через {days_after} дн. після активації. "
                    f"Оскільки це сталося протягом 30 днів, скасовано <b>{removed_xp} XP</b> реферального бонусу, отриманих за це запрошення.",
                    source="referral_clawback", dedupe_key=f"referral_clawback:{user.id}",
                )
        if user.status==UserStatus.ACTIVE.value:
            if user.registration_review_status != "approved":
                user.registration_review_status = "approved"
                user.registration_reviewed_at = clock.storage_utc()
                user.registration_reviewed_by = item.reviewed_by_label
                user.registration_rejection_reason = None
            await mark_registration_approved(session, user.id)
            await add_active_users_to_default_team(session)
            if not was_active: await reward_referral_if_ready(session,user,settings)
        await log_audit(session,"web_user_status_approve",actor_label=item.reviewed_by_label,entity_type="user",entity_id=user.id,details=f"{item.previous_status}->{item.requested_status}; requested by {item.requested_by_label}")
        await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}",303)


@router.post("/admin/users/{user_id}/status-request/{request_id}/reject")
async def user_status_request_reject(request: Request,user_id:int,request_id:int,review_note:str=Form("")):
    if r := guard_permission(request, "participants.approve"): return r
    async with db.session_factory() as session:
        item=await session.get(UserStatusChangeRequest,request_id)
        if not item or item.user_id!=user_id or item.status!="pending": raise HTTPException(404,"Запит не знайдено")
        item.status="rejected"; item.review_note=review_note.strip(); item.reviewed_by_label=request.session.get("admin_name","superadmin"); item.reviewed_at=clock.storage_utc()
        await log_audit(session,"web_user_status_reject",actor_label=item.reviewed_by_label,entity_type="user",entity_id=user_id,details=f"Відхилено {item.requested_status}; {item.review_note}")
        await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}",303)


@router.post("/admin/users/{user_id}/restoration/approve")
async def restoration_approve(request: Request, user_id: int):
    if r := guard_permission(request, "participants.approve"): return r
    async with db.session_factory() as session:
        user=await session.get(User,user_id)
        if not user or user.status != UserStatus.DELETED.value or user.restoration_request_status != "pending":
            raise HTTPException(409,"Немає активного запиту на відновлення")
        now=clock.storage_utc()
        user.status=UserStatus.ACTIVE.value
        user.restoration_request_status="approved"
        user.restoration_reviewed_at=now
        user.restoration_reviewed_by=request.session.get("admin_name","superadmin")
        user.restored_at=now
        user.probation_started_at=now
        user.probation_until=now+timedelta(days=14)
        user.last_activity_at=now
        await log_audit(session,"user_restoration_approved",actor_label=user.restoration_reviewed_by,entity_type="user",entity_id=user.id,details=f"Відновлено; випробувальний строк до {user.probation_until.isoformat()}")
        await queue_telegram_delivery(session,user.tg_id,"♻️ <b>Ваш акаунт відновлено!</b>\n\nДоступ до АМПасадорів відкрито. Від сьогодні діє 14-денний випробувальний строк: протягом нього потрібно мати хоча б одну підтверджену участь у події, квесті, волонтерській задачі, активності, опитуванні або подати ідею. Інакше акаунт буде видалено без можливості повторного відновлення.",source="restoration",dedupe_key=f"restoration:approved:{user.id}:{now.date().isoformat()}")
        await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}",303)


@router.post("/admin/users/{user_id}/restoration/reject")
async def restoration_reject(request: Request, user_id: int, review_note: str=Form("")):
    if r := guard_permission(request, "participants.approve"): return r
    async with db.session_factory() as session:
        user=await session.get(User,user_id)
        if not user or user.status != UserStatus.DELETED.value or user.restoration_request_status != "pending":
            raise HTTPException(409,"Немає активного запиту на відновлення")
        user.restoration_request_status="rejected"
        user.restoration_reviewed_at=clock.storage_utc()
        user.restoration_reviewed_by=request.session.get("admin_name","superadmin")
        await log_audit(session,"user_restoration_rejected",actor_label=user.restoration_reviewed_by,entity_type="user",entity_id=user.id,details=review_note.strip())
        await queue_telegram_delivery(session,user.tg_id,"❌ <b>Запит на відновлення акаунта не підтверджено.</b>\n\nЗа уточненнями зверніться до команди АМП.",source="restoration",dedupe_key=f"restoration:rejected:{user.id}:{user.restoration_reviewed_at.date().isoformat()}")
        await session.commit()
    return RedirectResponse(f"/admin/users/{user_id}",303)


@router.post("/admin/users/{user_id}/ban")
async def user_temporary_ban(request: Request, user_id: int, days: int = Form(7), reason: str = Form("Порушення правил спільноти")):
    """Compatibility endpoint. New bans are managed from /admin/moderation."""
    if r := guard_permission(request, "moderation.manage"): return r
    return await moderation_ban(request, user_id=user_id, days=days, reason=reason)


@router.post("/admin/users/{user_id}/unban")
async def user_unban(request: Request, user_id: int):
    """Compatibility endpoint for older links."""
    if r := guard_permission(request, "moderation.manage"): return r
    async with db.session_factory() as session:
        record = await session.scalar(
            select(BanRecord).where(BanRecord.user_id == user_id, BanRecord.lifted_at.is_(None)).order_by(BanRecord.started_at.desc())
        )
    if record:
        return await moderation_unban(request, record.id, lift_reason="Блокування знято вручну")
    return RedirectResponse("/admin/moderation", 303)


@router.get("/admin/moderation", response_class=HTMLResponse)
async def moderation(request: Request, q: str = ""):
    if r := guard_permission(request, "moderation.manage"): return r
    now = clock.storage_utc()
    async with db.session_factory() as session:
        expired = await process_expired_bans(session, now)
        if expired:
            await session.commit()
        users_stmt = select(User).where(User.role != UserRole.SUPERADMIN.value).order_by(User.full_name.asc())
        if q:
            like = f"%{q}%"
            users_stmt = users_stmt.where(or_(User.full_name.ilike(like), User.username.ilike(like), User.email.ilike(like)))
        users = (await session.scalars(users_stmt.limit(300))).all()
        active = (await session.scalars(
            select(BanRecord).where(BanRecord.lifted_at.is_(None), BanRecord.ends_at > now).order_by(BanRecord.ends_at.asc())
        )).all()
        history = (await session.scalars(select(BanRecord).order_by(BanRecord.started_at.desc()).limit(300))).all()
        ids = {r.user_id for r in history} | {r.issued_by_user_id for r in history if r.issued_by_user_id}
        people = {}
        if ids:
            people = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(ids)))).all()}
        return templates.TemplateResponse(
            request=request, name="moderation.html",
            context=ctx(request, users=users, active=active, history=history, people=people, now=now, q=q),
        )


@router.post("/admin/moderation/ban")
async def moderation_ban(request: Request, user_id: int = Form(...), days: int = Form(7), reason: str = Form(...)):
    if r := guard_permission(request, "moderation.manage"): return r
    days = max(1, min(int(days), 365))
    reason = reason.strip() or "Порушення правил спільноти"
    now = clock.storage_utc()
    ends_at = now + timedelta(days=days)
    notify_id = None
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Учасника не знайдено")
        if user.role == UserRole.SUPERADMIN.value:
            raise HTTPException(status_code=400, detail="Суперадміністратора не можна заблокувати через модуль модерації.")
        existing = await session.scalar(
            select(BanRecord).where(BanRecord.user_id == user.id, BanRecord.lifted_at.is_(None), BanRecord.ends_at > now).order_by(BanRecord.started_at.desc())
        )
        if existing:
            raise HTTPException(status_code=400, detail="У цього учасника вже є активне тимчасове блокування.")
        issuer = await session.scalar(select(User).where(User.role == UserRole.SUPERADMIN.value).order_by(User.id.asc()))
        record = BanRecord(
            user_id=user.id, issued_by_user_id=issuer.id if issuer else None, source="web", reason=reason,
            started_at=now, original_ends_at=ends_at, ends_at=ends_at, updated_at=now,
        )
        session.add(record)
        user.status = UserStatus.BLOCKED.value
        user.blocked_until = ends_at
        user.block_reason = reason
        notify_id = user.tg_id
        await session.flush()
        await log_audit(session, "web_user_temp_ban", actor_label=request.session.get("admin_name","web"), entity_type="ban_record", entity_id=record.id, details=f"АМП-{user.id:04d}; {days} дн.; {reason}")
        await session.commit()
    await notify_telegram(notify_id, f"⛔ <b>Тимчасове обмеження профілю</b>\nПричина: {reason}\nСтрок: {days} дн.\nДо: {ends_at.strftime('%d.%m.%Y %H:%M')}\n\nЯкщо вважаєте рішення помилковим — зверніться до команди АМП.")
    return RedirectResponse("/admin/moderation", 303)


@router.post("/admin/moderation/{record_id}/unban")
async def moderation_unban(request: Request, record_id: int, lift_reason: str = Form("Блокування знято суперадміністратором")):
    if r := guard_permission(request, "moderation.manage"): return r
    notify_id = None
    now = clock.storage_utc()
    async with db.session_factory() as session:
        record = await session.get(BanRecord, record_id)
        if not record:
            raise HTTPException(status_code=404, detail="Запис блокування не знайдено")
        user = await session.get(User, record.user_id)
        record.lifted_at = now
        record.lift_reason = (lift_reason or "Блокування знято").strip()
        record.updated_at = now
        if user:
            user.status = UserStatus.ACTIVE.value
            user.blocked_until = None
            user.block_reason = None
            notify_id = user.tg_id
        await log_audit(session, "web_user_unban", actor_label=request.session.get("admin_name","web"), entity_type="ban_record", entity_id=record.id, details=record.lift_reason)
        await session.commit()
    await notify_telegram(notify_id, "✅ Тимчасове обмеження вашого профілю знято. Ви знову можете користуватися можливостями АМП.")
    return RedirectResponse("/admin/moderation", 303)


@router.post("/admin/moderation/{record_id}/shorten")
async def moderation_shorten(request: Request, record_id: int, remaining_days: int = Form(...)):
    if r := guard_permission(request, "moderation.manage"): return r
    remaining_days = max(1, min(int(remaining_days), 365))
    now = clock.storage_utc()
    new_end = now + timedelta(days=remaining_days)
    notify_id = None
    async with db.session_factory() as session:
        record = await session.get(BanRecord, record_id)
        if not record or record.lifted_at is not None:
            raise HTTPException(status_code=404, detail="Активне блокування не знайдено")
        if new_end >= record.ends_at:
            raise HTTPException(status_code=400, detail="Новий строк має бути коротшим за поточний.")
        user = await session.get(User, record.user_id)
        record.ends_at = new_end
        record.updated_at = now
        if user:
            user.blocked_until = new_end
            notify_id = user.tg_id
        await log_audit(session, "web_user_ban_shorten", actor_label=request.session.get("admin_name","web"), entity_type="ban_record", entity_id=record.id, details=f"Новий строк до {new_end.strftime('%d.%m.%Y %H:%M')}")
        await session.commit()
    await notify_telegram(notify_id, f"ℹ️ Строк тимчасового обмеження скорочено. Новий строк: до {new_end.strftime('%d.%m.%Y %H:%M')}.")
    return RedirectResponse("/admin/moderation", 303)

