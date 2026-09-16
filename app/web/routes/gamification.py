from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
from app.web.dependencies import (
    Badge, File, Form, GOAL_METRIC_LABELS, Goal, GoalReward, HTMLResponse, HTTPException, LEAGUES, ParticipationStreak, RedirectResponse, Request, Reward, RewardClaim, Season, StreakFreeze, UploadFile, User, UserBadge, UserRole, UserStatus, create_streak_freeze, ctx, current_season, date, datetime, db, delete, delete_image, delete_stored_image, func, goal_progress, guard, has_web_permission, league_for_xp, log_audit, notify_telegram, opt_int, refresh_all_streaks, refresh_user_streak, save_badge_png, save_image, season_leaderboard_rows, season_xp, select, streak_freeze_summary, templates
)
from app.season_history import finalize_season, season_snapshot
from app.runtime_config import get_runtime_int
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

router = APIRouter()

@router.get("/admin/leaderboard", response_class=HTMLResponse)
async def leaderboard_dashboard(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        season = await current_season(session)
        if not season:
            return templates.TemplateResponse(
                request=request, name="leaderboard.html",
                context=ctx(request, season=None, overall=[], leagues=[], streak_rows=[], stats={}),
            )
        await refresh_all_streaks(session)
        await session.commit()
        overall = await season_leaderboard_rows(session, season, limit=20)
        all_rows = await season_leaderboard_rows(session, season)
        league_map = {item.code: [] for item in LEAGUES}
        for row in all_rows:
            league_map[league_for_xp(int(row[2] or 0)).code].append(row)
        league_sections = [
            {"league": lg, "rows": league_map[lg.code][:10], "count": len(league_map[lg.code])}
            for lg in LEAGUES
        ]
        streak_rows = (await session.execute(
            select(User, ParticipationStreak)
            .outerjoin(ParticipationStreak, ParticipationStreak.user_id == User.id)
            .where(User.status == UserStatus.ACTIVE.value)
            .order_by(
                func.coalesce(ParticipationStreak.event_streak, 0).desc(),
                func.coalesce(ParticipationStreak.weekly_streak, 0).desc(),
                User.full_name.asc(),
            )
        )).all()
        streak_count = sum(1 for _, st in streak_rows if st and int(st.weekly_streak or 0) > 0)
        super_count = sum(1 for _, st in streak_rows if st and int(st.event_streak or 0) > 0)
        best_weekly = max([int(st.weekly_best or 0) for _, st in streak_rows if st] or [0])
        best_event = max([int(st.event_best or 0) for _, st in streak_rows if st] or [0])
        freeze_map = await streak_freeze_summary(session, [u.id for u, _ in streak_rows])
        freeze_limit = await get_runtime_int(session, "streak.freeze_limit_quarter")
        frozen_now = sum(1 for item in freeze_map.values() if item.get("active_until"))
        stats = {
            "participants": len(all_rows),
            "weekly_active": streak_count,
            "super_active": super_count,
            "best_weekly": best_weekly,
            "best_event": best_event,
            "frozen_now": frozen_now,
        }
        return templates.TemplateResponse(
            request=request, name="leaderboard.html",
            context=ctx(request, season=season, overall=overall, leagues=league_sections,
                        streak_rows=streak_rows, stats=stats, league_for_xp=league_for_xp,
                        freeze_map=freeze_map, freeze_limit=freeze_limit),
        )


@router.get("/admin/streaks/{user_id}", response_class=HTMLResponse)
async def streak_detail(request: Request, user_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Учасника не знайдено")
        streak, _ = await refresh_user_streak(session, user)
        season = await current_season(session)
        sxp = await season_xp(session, user.id, season.id if season else None)
        freeze_limit = await get_runtime_int(session, "streak.freeze_limit_quarter")
        freeze = (await streak_freeze_summary(session, [user.id])).get(
            user.id, {"active_until": None, "used": 0, "remaining": freeze_limit}
        )
        history = list((await session.scalars(
            select(StreakFreeze).where(StreakFreeze.user_id == user.id)
            .order_by(StreakFreeze.starts_at.desc(), StreakFreeze.id.desc()).limit(40)
        )).all())
        await session.commit()
        return templates.TemplateResponse(
            request=request, name="streak_detail.html",
            context=ctx(request, user=user, streak=streak, freeze=freeze, freeze_history=history,
                        freeze_limit=freeze_limit, season=season, season_xp=sxp,
                        league=league_for_xp(sxp)),
        )


@router.post("/admin/streaks/{user_id}/update")
async def streak_update(
    request: Request,
    user_id: int,
    weekly_streak: int = Form(0),
    weekly_best: int = Form(0),
    event_streak: int = Form(0),
    event_best: int = Form(0),
    event_consecutive_misses: int = Form(0),
    event_total_misses: int = Form(0),
    event_started_at: str = Form(""),
    manual_note: str = Form(""),
):
    if r := guard(request): return r
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return HTMLResponse("Учасника не знайдено", status_code=404)
        row = await session.scalar(select(ParticipationStreak).where(ParticipationStreak.user_id == user_id))
        if not row:
            row = ParticipationStreak(user_id=user_id)
            session.add(row)
            await session.flush()
        row.weekly_streak = max(0, int(weekly_streak or 0))
        row.weekly_best = max(row.weekly_streak, int(weekly_best or 0))
        row.event_streak = max(0, int(event_streak or 0))
        row.event_best = max(row.event_streak, int(event_best or 0))
        consecutive_limit = await get_runtime_int(session, "streak.super_consecutive_misses")
        total_limit = await get_runtime_int(session, "streak.super_total_misses")
        row.event_consecutive_misses = max(0, min(consecutive_limit, int(event_consecutive_misses or 0)))
        row.event_total_misses = max(0, min(total_limit, int(event_total_misses or 0)))
        raw = event_started_at.strip()
        if raw:
            try:
                row.event_started_at = datetime.fromisoformat(raw)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Некоректна дата початку серії") from exc
        elif row.event_streak <= 0:
            row.event_started_at = None
        row.manual_lock = True
        row.manual_note = manual_note.strip()
        row.updated_at = clock.storage_utc()
        await log_audit(
            session, "web_streak_manual_update", actor_label=request.session.get("admin_name", "web"),
            entity_type="user", entity_id=user_id,
            details=f"Тижнева={row.weekly_streak}; суперсерія={row.event_streak}; пропуски={row.event_total_misses}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/streaks/{user_id}", status_code=303)


@router.post("/admin/streaks/{user_id}/freeze")
async def streak_freeze(
    request: Request,
    user_id: int,
    days: int = Form(...),
    freeze_note: str = Form(""),
):
    if r := guard(request): return r
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return HTMLResponse("Учасника не знайдено", status_code=404)
        try:
            row = await create_streak_freeze(
                session, user_id, days,
                created_by_label=request.session.get("admin_name", "web"),
                note=freeze_note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await log_audit(
            session, "web_streak_freeze", actor_label=request.session.get("admin_name", "web"),
            entity_type="user", entity_id=user_id,
            details=f"Заморожено на {row.days} дн. до {row.ends_at.strftime('%d.%m.%Y %H:%M')}; квартал {row.quarter_key}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/streaks/{user_id}", status_code=303)


@router.post("/admin/streaks/{user_id}/rebuild")
async def streak_rebuild(request: Request, user_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return HTMLResponse("Учасника не знайдено", status_code=404)
        row, _ = await refresh_user_streak(session, user, rebuild_events=True)
        await log_audit(
            session, "web_streak_rebuild", actor_label=request.session.get("admin_name", "web"),
            entity_type="user", entity_id=user_id,
            details=f"Перераховано з історії: тижнева={row.weekly_streak}; суперсерія={row.event_streak}",
        )
        await session.commit()
    return RedirectResponse(f"/admin/streaks/{user_id}", status_code=303)


@router.post("/admin/streaks/rebuild-all")
async def streak_rebuild_all(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        users = (await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value))).all()
        for user in users:
            await refresh_user_streak(session, user, rebuild_events=True)
        await log_audit(
            session, "web_streak_rebuild_all", actor_label=request.session.get("admin_name", "web"),
            entity_type="system", details=f"Перераховано серії для {len(users)} учасників",
        )
        await session.commit()
    return RedirectResponse("/admin/leaderboard#streaks", status_code=303)


@router.get("/admin/goals", response_class=HTMLResponse)
async def goals_page(request: Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        goals=list((await session.scalars(select(Goal).order_by(Goal.active.desc(), Goal.created_at.desc()))).all())
        users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value).order_by(User.full_name.asc()))).all())
        reward_counts=dict((await session.execute(select(GoalReward.goal_id, func.count(GoalReward.id)).group_by(GoalReward.goal_id))).all())
        rows=[]
        for g in goals:
            rows.append((g, await goal_progress(session,g,None), int(reward_counts.get(g.id,0))))
        return templates.TemplateResponse(request=request, name="goals.html", context=ctx(request, rows=rows, users=users, metric_labels=GOAL_METRIC_LABELS))


def _parse_goal_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некоректна дата/час цілі") from exc


@router.post("/admin/goals/create")
async def goals_create(
    request: Request,
    scope: str=Form("season"), title: str=Form(...), task_text: str=Form(...), description: str=Form(""),
    metric: str=Form("xp"), target_value: float=Form(1), reward_xp: int=Form(0), user_id: str=Form(""),
    starts_at: str=Form(""), ends_at: str=Form(""), photo: UploadFile | None=File(None),
):
    if r := guard(request): return r
    if scope not in {"season","personal","team"}: scope="season"
    if metric not in GOAL_METRIC_LABELS: metric="xp"
    start=_parse_goal_dt(starts_at) or clock.storage_utc(); end=_parse_goal_dt(ends_at)
    if end and end <= start:
        raise HTTPException(status_code=400, detail="Дедлайн має бути пізніше за початок")
    uid=int(user_id) if user_id.strip().isdigit() else None
    if scope=="personal" and not uid: raise HTTPException(status_code=400, detail="Для персональної цілі оберіть учасника")
    if scope!="personal": uid=None
    img=await save_image(photo,"goals")
    async with db.session_factory() as session:
        g=Goal(
            scope=scope,title=title.strip(),task_text=task_text.strip(),description=description.strip(),metric=metric,
            target_value=max(.01,target_value),reward_xp=max(0,min(int(reward_xp),500)),user_id=uid,
            starts_at=start,ends_at=end,active=True,image_path=img,
        )
        session.add(g); await session.flush()
        await log_audit(session,"web_goal_create",actor_label=request.session.get("admin_name","web"),entity_type="goal",entity_id=g.id,details=f"{g.title}; {g.metric}={g.target_value}; reward={g.reward_xp}")
        await session.commit()
    return RedirectResponse("/admin/goals",303)


@router.post("/admin/goals/{goal_id}/update")
async def goals_update(
    request: Request, goal_id: int,
    scope: str=Form("season"), title: str=Form(...), task_text: str=Form(...), description: str=Form(""),
    metric: str=Form("xp"), target_value: float=Form(1), reward_xp: int=Form(0), user_id: str=Form(""),
    starts_at: str=Form(""), ends_at: str=Form(""), photo: UploadFile | None=File(None), remove_photo: str|None=Form(None),
):
    if r := guard(request): return r
    if scope not in {"season","personal","team"}: scope="season"
    if metric not in GOAL_METRIC_LABELS: metric="xp"
    start=_parse_goal_dt(starts_at) or clock.storage_utc(); end=_parse_goal_dt(ends_at)
    if end and end <= start:
        raise HTTPException(status_code=400, detail="Дедлайн має бути пізніше за початок")
    uid=int(user_id) if user_id.strip().isdigit() else None
    if scope=="personal" and not uid: raise HTTPException(status_code=400, detail="Для персональної цілі оберіть учасника")
    if scope!="personal": uid=None
    new_img=await save_image(photo,"goals")
    async with db.session_factory() as session:
        g=await session.get(Goal,goal_id)
        if not g: raise HTTPException(status_code=404,detail="Ціль не знайдено")
        old_img=g.image_path
        if new_img:
            g.image_path=new_img
        elif remove_photo:
            g.image_path=None
        g.scope=scope; g.title=title.strip(); g.task_text=task_text.strip(); g.description=description.strip(); g.metric=metric
        g.target_value=max(.01,target_value); g.reward_xp=max(0,min(int(reward_xp),500)); g.user_id=uid; g.starts_at=start; g.ends_at=end
        await log_audit(session,"web_goal_update",actor_label=request.session.get("admin_name","web"),entity_type="goal",entity_id=g.id,details=f"{g.title}; {g.metric}={g.target_value}; reward={g.reward_xp}")
        await session.commit()
    if old_img and old_img != g.image_path:
        await delete_stored_image(db, old_img)
    return RedirectResponse("/admin/goals",303)


@router.post("/admin/goals/{goal_id}/toggle")
async def goals_toggle(request: Request, goal_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        g=await session.get(Goal,goal_id)
        if g: g.active=not g.active; await log_audit(session,"web_goal_toggle",actor_label=request.session.get("admin_name","web"),entity_type="goal",entity_id=g.id,details=f"active={g.active}"); await session.commit()
    return RedirectResponse("/admin/goals",303)


@router.post("/admin/goals/{goal_id}/delete")
async def goals_delete(request: Request, goal_id: int):
    if r := guard(request): return r
    img=None
    async with db.session_factory() as session:
        g=await session.get(Goal,goal_id)
        if g:
            img=g.image_path
            await log_audit(session,"web_goal_delete",actor_label=request.session.get("admin_name","web"),entity_type="goal",entity_id=g.id,details=g.title)
            await session.execute(delete(GoalReward).where(GoalReward.goal_id==g.id))
            await session.delete(g); await session.commit()
    if img: await delete_stored_image(db,img)
    return RedirectResponse("/admin/goals",303)


@router.get("/admin/badges", response_class=HTMLResponse)
async def badges(request:Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        rows=(await session.scalars(select(Badge).order_by(Badge.badge_type.asc(), Badge.automatic.desc(),Badge.name))).all()
        users=(await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value).order_by(User.full_name.asc()))).all()
        return templates.TemplateResponse(request=request,name="badges.html",context=ctx(request,rows=rows,users=users))


@router.post("/admin/badges/create")
async def badge_create(
    request:Request,name:str=Form(...),icon:str=Form("🏅"),description:str=Form(""),criteria_type:str=Form(""),criteria_value:str=Form(""),
    automatic:str|None=Form(None),active:str|None=Form(None),badge_type:str=Form("general"),badge_png:UploadFile|None=File(None)
):
    if r := guard(request): return r
    badge_type = badge_type if badge_type in {"general","ambassador"} else "general"
    image_path = await save_badge_png(badge_png) if badge_type == "ambassador" else None
    async with db.session_factory() as session:
        b=Badge(name=name.strip(),icon=icon or "🏅",description=description.strip(),criteria_type=criteria_type or None,criteria_value=opt_int(criteria_value),automatic=bool(automatic),active=bool(active),image_path=image_path,badge_type=badge_type)
        session.add(b); await session.flush(); await log_audit(session,"web_badge_create",actor_label=request.session.get("admin_name","web"),entity_type="badge",entity_id=b.id,details=f"{name}; type={badge_type}"); await session.commit()
    return RedirectResponse("/admin/badges",303)


@router.post("/admin/badges/{badge_id}/update")
async def badge_update(
    request:Request,badge_id:int,name:str=Form(...),icon:str=Form("🏅"),description:str=Form(""),criteria_type:str=Form(""),criteria_value:str=Form(""),
    automatic:str|None=Form(None),active:str|None=Form(None),badge_type:str=Form("general"),remove_image:str|None=Form(None),badge_png:UploadFile|None=File(None)
):
    if r := guard(request): return r
    badge_type = badge_type if badge_type in {"general","ambassador"} else "general"
    async with db.session_factory() as session:
        b=await session.get(Badge,badge_id)
        if b:
            donation_criteria = {"donation_first", "donation_single", "donation_total_over"}
            if b.criteria_type in donation_criteria:
                # Built-in donation badges are system rules. Keep their criterion,
                # threshold, automatic flag and type protected from crafted form posts.
                b.active = True
            else:
                b.name=name.strip(); b.icon=icon or "🏅"; b.description=description.strip(); b.criteria_type=criteria_type or None; b.criteria_value=opt_int(criteria_value); b.automatic=bool(automatic); b.active=bool(active); b.badge_type=badge_type
            if b.criteria_type not in donation_criteria:
                if badge_type == "general" and b.image_path:
                    await delete_image(b.image_path); b.image_path=None
                elif remove_image and b.image_path:
                    await delete_image(b.image_path); b.image_path=None
                if badge_type == "ambassador":
                    img=await save_badge_png(badge_png)
                    if img:
                        if b.image_path: await delete_image(b.image_path)
                        b.image_path=img
            await log_audit(session,"web_badge_update",actor_label=request.session.get("admin_name","web"),entity_type="badge",entity_id=b.id,details=f"{b.name}; type={b.badge_type}"); await session.commit()
    return RedirectResponse("/admin/badges",303)


@router.post("/admin/badges/award-batch")
async def badge_award_batch(request: Request):
    if r := guard(request): return r
    form = await request.form()
    badge_id = opt_int(str(form.get("badge_id") or ""))
    selected = [int(v) for v in form.getlist("user_ids") if str(v).isdigit()]
    if not badge_id or not selected:
        raise HTTPException(status_code=400, detail="Оберіть бейдж і щонайменше одного учасника.")
    notifications=[]
    async with db.session_factory() as session:
        badge=await session.get(Badge,badge_id)
        if not badge: raise HTTPException(status_code=404, detail="Бейдж не знайдено")
        users=list((await session.scalars(select(User).where(User.id.in_(selected),User.status==UserStatus.ACTIVE.value))).all())
        awarded=0
        actor_label=request.session.get("admin_name","web")
        for user in users:
            if badge.badge_type=="ambassador" and user.role not in {UserRole.AMBASSADOR.value,UserRole.COORDINATOR.value,UserRole.ADMIN.value,UserRole.SUPERADMIN.value}:
                continue
            exists=await session.scalar(select(UserBadge).where(UserBadge.user_id==user.id,UserBadge.badge_id==badge.id))
            if exists: continue
            session.add(UserBadge(user_id=user.id,badge_id=badge.id,awarded_by=None))
            notifications.append((user.tg_id,user.full_name)); awarded+=1
        await log_audit(session,"web_badge_award_batch",actor_label=actor_label,entity_type="badge",entity_id=badge.id,details=f"Видано {awarded} учасникам: {badge.name}")
        await session.commit()
    for tg_id,_ in notifications:
        await notify_telegram(tg_id,f"🏅 <b>Новий бейдж!</b>\n{badge.icon} <b>{badge.name}</b>\n{badge.description}")
    return RedirectResponse("/admin/badges",303)


@router.get("/admin/rewards", response_class=HTMLResponse)
async def rewards(request:Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        rows=(await session.scalars(select(Reward).order_by(Reward.active.desc(),Reward.min_xp))).all()
        claims=(await session.execute(select(RewardClaim,User,Reward).join(User,User.id==RewardClaim.user_id).join(Reward,Reward.id==RewardClaim.reward_id).where(RewardClaim.status=="requested").order_by(RewardClaim.requested_at.asc()))).all()
        return templates.TemplateResponse(request=request,name="rewards.html",context=ctx(request,rows=rows,claims=claims))


@router.post("/admin/rewards/create")
async def reward_create(request:Request,title:str=Form(...),description:str=Form(""),min_xp:int=Form(0),stock:str=Form(""),reward_type:str=Form("item"),active:str|None=Form(None),photo:UploadFile|None=File(None)):
    if r := guard(request): return r
    img=await save_image(photo,"rewards")
    async with db.session_factory() as session:
        rw=Reward(title=title,description=description,min_xp=max(0,min_xp),stock=opt_int(stock),active=bool(active),image_path=img,reward_type=reward_type if reward_type in {"item","service","streak_restore"} else "item"); session.add(rw); await session.flush(); await log_audit(session,"web_reward_create",actor_label=request.session.get("admin_name","web"),entity_type="reward",entity_id=rw.id,details=title); await session.commit()
    return RedirectResponse("/admin/rewards",303)


@router.post("/admin/rewards/{reward_id}/update")
async def reward_update(request:Request,reward_id:int,title:str=Form(...),description:str=Form(""),min_xp:int=Form(0),stock:str=Form(""),reward_type:str=Form("item"),active:str|None=Form(None),remove_image:str|None=Form(None),photo:UploadFile|None=File(None)):
    if r := guard(request): return r
    async with db.session_factory() as session:
        rw=await session.get(Reward,reward_id)
        if rw:
            rw.title=title; rw.description=description; rw.min_xp=max(0,min_xp); rw.stock=opt_int(stock); rw.active=bool(active); rw.reward_type=reward_type if reward_type in {"item","service","streak_restore"} else "item"
            if remove_image: await delete_image(rw.image_path); rw.image_path=None
            img=await save_image(photo,"rewards")
            if img: await delete_image(rw.image_path); rw.image_path=img
            await log_audit(session,"web_reward_update",actor_label=request.session.get("admin_name","web"),entity_type="reward",entity_id=rw.id,details=title); await session.commit()
    return RedirectResponse("/admin/rewards",303)


@router.post("/admin/reward-claims/{claim_id}/{action}")
async def reward_claim_action(request:Request,claim_id:int,action:str):
    if r := guard(request): return r
    async with db.session_factory() as session:
        c=await session.get(RewardClaim,claim_id)
        if c and c.status=="requested":
            u=await session.get(User,c.user_id); rw=await session.get(Reward,c.reward_id)
            if action=="fulfill":
                c.status="fulfilled"; c.fulfilled_at=clock.storage_utc()
            elif action=="reject":
                c.status="rejected"
                if u: u.wallet_xp += int(c.xp_spent or 0)
                if rw and rw.stock is not None: rw.stock += 1
            await log_audit(session,f"web_reward_{action}",actor_label=request.session.get("admin_name","web"),entity_type="reward_claim",entity_id=c.id,details=f"xp={c.xp_spent}"); await session.commit()
    return RedirectResponse("/admin/rewards",303)


@router.get("/admin/seasons", response_class=HTMLResponse)
async def seasons(request:Request):
    if r := guard(request): return r
    async with db.session_factory() as session:
        rows=list((await session.scalars(select(Season).order_by(Season.starts_at.desc()))).all())
        summaries={s.id: season_snapshot(s) for s in rows}
        return templates.TemplateResponse(request=request,name="seasons.html",context=ctx(request,rows=rows,summaries=summaries))


@router.get("/admin/seasons/{season_id}", response_class=HTMLResponse)
async def season_history_detail(request: Request, season_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        season=await session.get(Season,season_id)
        if not season: raise HTTPException(status_code=404,detail="Сезон не знайдено")
        snapshot=season_snapshot(season)
        if not snapshot and (season.archived or season.ends_at < clock.today_local()):
            snapshot=await finalize_season(session,season); await session.commit()
        return templates.TemplateResponse(request=request,name="season_detail.html",context=ctx(request,season=season,snapshot=snapshot))


@router.post("/admin/seasons/{season_id}/finalize")
async def season_finalize(request: Request, season_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        season=await session.get(Season,season_id)
        if not season: raise HTTPException(status_code=404,detail="Сезон не знайдено")
        await finalize_season(session,season,force=True)
        await log_audit(session,"web_season_finalize",actor_label=request.session.get("admin_name","web"),entity_type="season",entity_id=season.id,details=season.name)
        await session.commit()
    return RedirectResponse(f"/admin/seasons/{season_id}",303)


@router.post("/admin/seasons/create")
async def season_create(request:Request,name:str=Form(...),starts_at:str=Form(...),ends_at:str=Form(...)):
    if r := guard(request): return r
    start=date.fromisoformat(starts_at); end=date.fromisoformat(ends_at)
    if end<start: return RedirectResponse("/admin/seasons?error=dates",303)
    async with db.session_factory() as session:
        for s in (await session.scalars(select(Season).where(Season.active==True))).all():  # noqa
            await finalize_season(session,s)
        season=Season(name=name,starts_at=start,ends_at=end,active=True,archived=False); session.add(season); await session.flush()
        await log_audit(session,"web_season_create",actor_label=request.session.get("admin_name","web"),entity_type="season",entity_id=season.id,details=f"{start}..{end}"); await session.commit()
    return RedirectResponse("/admin/seasons",303)


@router.get("/admin/gamification/insights", response_class=HTMLResponse)
async def gamification_insights_page(request: Request):
    if r := guard(request):
        return r
    if not (has_web_permission(request, "analytics.view") or has_web_permission(request, "gamification.manage")):
        return HTMLResponse("<h1>403</h1><p>Недостатньо прав для аналітики гейміфікації.</p>", status_code=403)
    from app.gamification_insights import build_gamification_insights
    async with db.session_factory() as session:
        insights = await build_gamification_insights(session)
        await session.commit()
    return templates.TemplateResponse(
        request=request, name="gamification_insights.html",
        context=ctx(request, insights=insights),
    )
