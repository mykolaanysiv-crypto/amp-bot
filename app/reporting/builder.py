from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ActivityApplication, Event, EventRegistration, EventFeedback, Idea, OpportunityInterest, ParticipationStreak, Quest, RegistrationJourney,
    QuestParticipation, RequestCase, Season, StreakFreeze, Survey, SurveyResponse, User, UserBadge, VolunteerTask, VolunteerTaskParticipation,
    XPTransaction,
)
from ..profile_data import CODE_TO_LABEL, gender_label, load_vulnerabilities
from ..leagues import LEAGUES, league_for_xp
from ..runtime_config import get_runtime_int
from ..settlements import canonicalize_settlement_text, settlement_quality_report
from ..time_utils import clock
from .periods import _age, _age_group, _next_month, resolve_report_storage_bounds

async def build_period_report(session: AsyncSession, start: datetime, end: datetime, label: str, *, reveal_sensitive_counts: bool = False) -> dict[str, Any]:
    # Report selection is a local-calendar concept; persisted operational timestamps
    # are UTC. Convert boundaries once so midnight and DST do not leak records into
    # the neighbouring local day/month. Event.starts_at remains legacy local-wall.
    generated_at_utc = clock.now_utc()
    generated_at = clock.local_wall(generated_at_utc)
    start_utc, end_utc = resolve_report_storage_bounds(start, end)

    def _storage_to_local(value: datetime | None) -> datetime | None:
        aware = clock.from_storage_utc(value)
        return clock.local_wall(aware) if aware else None
    privacy_threshold = await get_runtime_int(session, "privacy.suppression_threshold")
    checkin_close_minutes = await get_runtime_int(session, "events.checkin_close_after_minutes")
    users=list((await session.scalars(select(User))).all())
    events=list((await session.scalars(select(Event).where(Event.starts_at>=start, Event.starts_at<end))).all())
    report_events=[e for e in events if e.status not in {"cancelled","draft"} and not e.cancelled_at]
    upcoming_events=[e for e in report_events if e.starts_at > generated_at]
    completed_events=[
        e for e in report_events
        if e.starts_at <= generated_at
        and (e.status == "completed" or e.starts_at + timedelta(minutes=checkin_close_minutes) < generated_at)
    ]
    in_progress_events=[e for e in report_events if e not in completed_events and e not in upcoming_events]
    completed_event_ids={e.id for e in completed_events}
    event_ids=[e.id for e in report_events]
    regs=list((await session.scalars(select(EventRegistration).where(EventRegistration.event_id.in_(event_ids) if event_ids else EventRegistration.id==-1))).all())
    attended=[r for r in regs if r.status=="attended" and r.event_id in completed_event_ids]
    quests=list((await session.scalars(select(Quest))).all())
    qparts=list((await session.scalars(select(QuestParticipation).where(QuestParticipation.status=="approved", QuestParticipation.approved_at>=start_utc, QuestParticipation.approved_at<end_utc))).all())
    tasks=list((await session.scalars(select(VolunteerTask))).all())
    tparts=list((await session.scalars(select(VolunteerTaskParticipation).where(VolunteerTaskParticipation.status=="approved", VolunteerTaskParticipation.approved_at>=start_utc, VolunteerTaskParticipation.approved_at<end_utc))).all())
    apps=list((await session.scalars(select(ActivityApplication).where(ActivityApplication.completed_at>=start_utc, ActivityApplication.completed_at<end_utc))).all())
    ideas=list((await session.scalars(select(Idea).where(Idea.created_at>=start_utc, Idea.created_at<end_utc))).all())
    implemented=list((await session.scalars(select(Idea).where(Idea.status=="implemented", Idea.updated_at>=start_utc, Idea.updated_at<end_utc))).all())
    requests=list((await session.scalars(select(RequestCase).where(RequestCase.created_at>=start_utc, RequestCase.created_at<end_utc))).all())
    resolved_requests=list((await session.scalars(select(RequestCase).where(RequestCase.resolved_at>=start_utc, RequestCase.resolved_at<end_utc))).all())
    txs=list((await session.scalars(select(XPTransaction).where(XPTransaction.created_at>=start_utc, XPTransaction.created_at<end_utc))).all())
    interests=list((await session.scalars(select(OpportunityInterest).where(OpportunityInterest.created_at>=start_utc, OpportunityInterest.created_at<end_utc, OpportunityInterest.status=="interested"))).all())
    all_surveys=list((await session.scalars(select(Survey))).all())
    surveys=[]
    for sv in all_surveys:
        survey_stamp = sv.starts_at if sv.starts_at else _storage_to_local(sv.created_at)
        if survey_stamp and start <= survey_stamp < end and sv.status in {"published","closed"}:
            surveys.append(sv)
    survey_responses=list((await session.scalars(select(SurveyResponse).where(SurveyResponse.completed_at>=start_utc, SurveyResponse.completed_at<end_utc))).all())
    user_badges=list((await session.scalars(select(UserBadge).where(UserBadge.awarded_at>=start_utc, UserBadge.awarded_at<end_utc))).all())
    feedback_rows=list((await session.scalars(select(EventFeedback).where(EventFeedback.completed_at>=start_utc, EventFeedback.completed_at<end_utc, EventFeedback.status=="completed"))).all())
    freeze_rows=list((await session.scalars(select(StreakFreeze).where(StreakFreeze.starts_at>=start_utc, StreakFreeze.starts_at<end_utc))).all())
    streak_rows=list((await session.scalars(select(ParticipationStreak))).all())
    active_season=await session.scalar(select(Season).where(Season.active==True).order_by(Season.starts_at.desc()))  # noqa: E712
    new_users=[u for u in users if start_utc <= u.created_at < end_utc]

    event_by={e.id:e for e in report_events}; task_by={t.id:t for t in tasks}
    event_attendance=Counter(r.event_id for r in attended)
    event_hours=sum(float(event_by[r.event_id].volunteer_hours or 0) for r in attended if r.event_id in event_by)
    task_hours=sum(float(task_by[p.task_id].hours_reward or 0) for p in tparts if p.task_id in task_by)
    activity_hours=sum(float(a.hours_reward or 0) for a in apps)

    engaged_ids=set(r.user_id for r in attended)
    engaged_ids.update(p.user_id for p in qparts)
    engaged_ids.update(p.user_id for p in tparts)
    engaged_ids.update(a.user_id for a in apps)
    engaged_ids.update(i.user_id for i in ideas)
    engaged_ids.update(c.user_id for c in requests)
    engaged_ids.update(r.user_id for r in survey_responses)
    cohort=[u for u in users if u.id in engaged_ids]

    gender=Counter(gender_label(u.gender) for u in cohort)
    age_reference=min(generated_at.date(), (end - timedelta(microseconds=1)).date())
    age=Counter(_age_group(_age(u.birth_date, age_reference)) for u in cohort)
    settlement=Counter(canonicalize_settlement_text(u.settlement) or "Не зазначено" for u in cohort)
    vuln_raw=Counter()
    for u in cohort:
        codes,_=load_vulnerabilities(u.vulnerability_categories)
        if not codes:
            vuln_raw["Не зазначено / не бажає повідомляти"]+=1
        else:
            for code in codes:
                vuln_raw["Інша категорія" if code=="other" else CODE_TO_LABEL.get(code,code)]+=1
    # Row-level sensitive data is never exported here. For ordinary staff, small
    # aggregate groups are suppressed; a superadmin may explicitly request exact
    # aggregate counts while still receiving no participant names/contacts.
    def _suppressed(count: int) -> bool:
        return (not reveal_sensitive_counts) and 0 < int(count) < privacy_threshold
    vuln=Counter({label:(0 if _suppressed(count) else int(count)) for label,count in vuln_raw.items()})
    vuln_display={label:(f"<{privacy_threshold}" if _suppressed(count) else str(int(count))) for label,count in vuln_raw.items()}

    event_rows=[]
    for e in sorted(report_events,key=lambda x:x.starts_at):
        if e in completed_events:
            timing_state, timing_label = "completed", "Завершена"
        elif e in upcoming_events:
            timing_state, timing_label = "upcoming", "Майбутня"
        else:
            timing_state, timing_label = "in_progress", "Триває"
        event_rows.append({
            "title":e.title,"date":e.starts_at.strftime("%d.%m.%Y %H:%M"),"location":e.location,"status":e.status,
            "timing_state":timing_state,"timing_label":timing_label,
            "attended":event_attendance.get(e.id,0) if timing_state=="completed" else 0,
            "registered":sum(1 for r in regs if r.event_id==e.id and r.status!="cancelled"),
        })
    future_attendance_anomalies=sum(1 for r in regs if r.status=="attended" and r.event_id not in completed_event_ids)

    # Monthly trend within selected interval.
    monthly=[]; y,m=start.year,start.month
    while datetime(y,m,1)<end:
        ny,nm=_next_month(y,m); ms=datetime(y,m,1); me=datetime(ny,nm,1)
        ms_utc, me_utc = clock.local_period_to_storage_utc(ms, me)
        monthly.append({
            "label":f"{m:02d}.{y}",
            "events":sum(1 for e in completed_events if ms<=e.starts_at<me),
            "planned_events":sum(1 for e in report_events if ms<=e.starts_at<me),
            "visits":sum(1 for r in attended if (event_by.get(r.event_id) and ms<=event_by[r.event_id].starts_at<me)),
            "new_users":sum(1 for u in new_users if ms_utc<=u.created_at<me_utc),
            "xp":sum(max(0,int(t.amount or 0)) for t in txs if ms_utc<=t.created_at<me_utc),
            "survey_responses":sum(1 for r in survey_responses if ms_utc<=r.completed_at<me_utc),
            "badges":sum(1 for r in user_badges if ms_utc<=r.awarded_at<me_utc),
        })
        y,m=ny,nm

    # Reporting 2.0: choose a meaningful granularity instead of plotting a
    # one-point monthly line for short periods. Up to 31 days -> daily, up to
    # 120 days -> weekly, otherwise monthly.
    span_days = max(1, int((end - start).total_seconds() // 86400))
    if span_days <= 31:
        trend_granularity = "day"
        trend_granularity_label = "по днях"
        buckets=[]
        cursor=start
        while cursor < end:
            bucket_end=min(cursor+timedelta(days=1), end)
            buckets.append((cursor,bucket_end,cursor.strftime("%d.%m")))
            cursor=bucket_end
    elif span_days <= 120:
        trend_granularity = "week"
        trend_granularity_label = "по тижнях"
        buckets=[]
        cursor=start
        while cursor < end:
            bucket_end=min(cursor+timedelta(days=7), end)
            buckets.append((cursor,bucket_end,f"{cursor.strftime('%d.%m')}–{(bucket_end-timedelta(seconds=1)).strftime('%d.%m')}"))
            cursor=bucket_end
    else:
        trend_granularity = "month"
        trend_granularity_label = "по місяцях"
        buckets=[]
        y,m=start.year,start.month
        while datetime(y,m,1)<end:
            ny,nm=_next_month(y,m); bs=max(start,datetime(y,m,1)); be=min(end,datetime(ny,nm,1))
            buckets.append((bs,be,f"{m:02d}.{y}")); y,m=ny,nm

    trend=[]
    for bs,be,bucket_label in buckets:
        bs_utc, be_utc = clock.local_period_to_storage_utc(bs, be)
        trend.append({
            "label":bucket_label,
            "events":sum(1 for e in completed_events if bs<=e.starts_at<be),
            "planned_events":sum(1 for e in report_events if bs<=e.starts_at<be),
            "visits":sum(1 for r in attended if (event_by.get(r.event_id) and bs<=event_by[r.event_id].starts_at<be)),
            "new_users":sum(1 for u in new_users if bs_utc<=u.created_at<be_utc),
            "xp":sum(max(0,int(t.amount or 0)) for t in txs if bs_utc<=t.created_at<be_utc),
            "survey_responses":sum(1 for r in survey_responses if bs_utc<=r.completed_at<be_utc),
            "badges":sum(1 for r in user_badges if bs_utc<=r.awarded_at<be_utc),
        })

    positive_xp=sum(int(t.amount or 0) for t in txs if int(t.amount or 0)>0)

    # Weekly badge dynamics inside the selected report period.
    badge_weekly_counter=Counter()
    for row in user_badges:
        local_awarded = _storage_to_local(row.awarded_at)
        if not local_awarded:
            continue
        monday=local_awarded.date()-timedelta(days=local_awarded.date().weekday())
        badge_weekly_counter[monday]+=1
    badge_weekly=[{"label":week.strftime("%d.%m.%Y"),"value":count} for week,count in sorted(badge_weekly_counter.items())]

    league_distribution={lg.title:0 for lg in LEAGUES}
    if active_season:
        xp_by_user=Counter()
        season_txs=list((await session.scalars(select(XPTransaction).where(XPTransaction.season_id==active_season.id))).all())
        for tx in season_txs: xp_by_user[tx.user_id]+=int(tx.amount or 0)
        for u in users:
            if getattr(u,"status",None)=="active":
                league_distribution[league_for_xp(xp_by_user.get(u.id,0)).title]+=1
    streak_snapshot={
        "weekly_active":sum(1 for r in streak_rows if int(r.weekly_streak or 0)>0),
        "super_active":sum(1 for r in streak_rows if int(r.event_streak or 0)>0),
        "recoverable":sum(1 for r in streak_rows if int(r.recoverable_event_streak or 0)>0),
        "best_weekly":max([int(r.weekly_best or 0) for r in streak_rows] or [0]),
        "best_event":max([int(r.event_best or 0) for r in streak_rows] or [0]),
    }
    def _pct_true(rows, attr: str) -> float:
        values=[getattr(row,attr,None) for row in rows if getattr(row,attr,None) is not None]
        return round(sum(1 for value in values if value)/len(values)*100,1) if values else 0.0

    ratings=[int(row.rating) for row in feedback_rows if row.rating is not None]
    feedback_avg_rating=round(sum(ratings)/len(ratings),2) if ratings else 0.0
    feedback_high_rating_pct=round(sum(1 for value in ratings if value>=4)/len(ratings)*100,1) if ratings else 0.0
    feedback_useful_pct=_pct_true(feedback_rows,"useful")
    feedback_new_knowledge_pct=_pct_true(feedback_rows,"new_knowledge")
    feedback_safe_pct=_pct_true(feedback_rows,"felt_safe")
    feedback_return_pct=_pct_true(feedback_rows,"would_return")
    outcomes={
        "responses":len(feedback_rows),
        "avg_rating":feedback_avg_rating,
        "high_rating_pct":feedback_high_rating_pct,
        "useful_pct":feedback_useful_pct,
        "new_knowledge_pct":feedback_new_knowledge_pct,
        "safe_pct":feedback_safe_pct,
        "return_pct":feedback_return_pct,
    }

    # v1.9.1 — donor/council-friendly advanced analytics.
    participant_users=[u for u in users if (getattr(u,"role",None) or "participant") in {"participant","ambassador"}]
    participant_ids={u.id for u in participant_users}
    all_event_regs=list((await session.scalars(select(EventRegistration).where(EventRegistration.status=="attended"))).all())
    all_event_ids={r.event_id for r in all_event_regs}
    all_events=list((await session.scalars(select(Event).where(Event.id.in_(all_event_ids) if all_event_ids else Event.id==-1))).all())
    all_event_by={e.id:e for e in all_events}
    visits_by_user=defaultdict(list)
    for reg in all_event_regs:
        if reg.user_id not in participant_ids:
            continue
        event=all_event_by.get(reg.event_id)
        stamp=event.starts_at if event and event.starts_at else (reg.confirmed_at or reg.checkin_at)
        if stamp:
            visits_by_user[reg.user_id].append(stamp)
    for values in visits_by_user.values(): values.sort()
    first_visit_ids={uid for uid,v in visits_by_user.items() if v}
    returned_ids={uid for uid,v in visits_by_user.items() if len(v)>=2}
    regular_ids={uid for uid,v in visits_by_user.items() if len(v)>=3 and len({(x.isocalendar().year,x.isocalendar().week) for x in v})>=3}
    ambassador_ids={u.id for u in participant_users if getattr(u,"role",None)=="ambassador"}
    cohort_funnel={
        "registered":len(participant_users),
        "first_visit":len(first_visit_ids),
        "returned":len(returned_ids),
        "regular":len(regular_ids),
        "ambassadors":len(regular_ids & ambassador_ids),
    }
    retention30=set(); retention90=set()
    for uid, visits in visits_by_user.items():
        if len(visits)<2: continue
        first=visits[0]
        if any(first < nxt <= first+timedelta(days=30) for nxt in visits[1:]): retention30.add(uid)
        if any(first < nxt <= first+timedelta(days=90) for nxt in visits[1:]): retention90.add(uid)
    retention_base=len(first_visit_ids)
    retention={
        "base":retention_base,
        "days30_count":len(retention30),
        "days30_pct":round(len(retention30)/retention_base*100,1) if retention_base else 0.0,
        "days90_count":len(retention90),
        "days90_pct":round(len(retention90)/retention_base*100,1) if retention_base else 0.0,
    }

    all_qparts=list((await session.scalars(select(QuestParticipation))).all())
    all_tparts=list((await session.scalars(select(VolunteerTaskParticipation))).all())
    all_apps=list((await session.scalars(select(ActivityApplication))).all())
    all_ideas=list((await session.scalars(select(Idea))).all())
    all_survey_responses=list((await session.scalars(select(SurveyResponse))).all())
    event_count=Counter(r.user_id for r in all_event_regs)
    quest_count=Counter(r.user_id for r in all_qparts if r.status=="approved")
    idea_count=Counter(r.user_id for r in all_ideas)
    survey_count=Counter(r.user_id for r in all_survey_responses)
    streak_by_user={row.user_id:int(row.weekly_streak or 0) for row in streak_rows}
    engagement_scores={}
    for u in participant_users:
        score=(min(streak_by_user.get(u.id,0)/4,1)*20 + min(event_count.get(u.id,0)/6,1)*25 + min(float(u.volunteer_hours or 0)/10,1)*20 + min(idea_count.get(u.id,0)/2,1)*10 + min(survey_count.get(u.id,0)/4,1)*10 + min(quest_count.get(u.id,0)/4,1)*15)
        engagement_scores[u.id]=int(round(score))
    engagement={
        "average":round(sum(engagement_scores.values())/len(engagement_scores),1) if engagement_scores else 0.0,
        "high":sum(1 for value in engagement_scores.values() if value>=75),
        "bands":{
            "0–24":sum(1 for value in engagement_scores.values() if 0<=value<=24),
            "25–49":sum(1 for value in engagement_scores.values() if 25<=value<=49),
            "50–74":sum(1 for value in engagement_scores.values() if 50<=value<=74),
            "75–100":sum(1 for value in engagement_scores.values() if 75<=value<=100),
        },
    }
    heatmap=[[0 for _ in range(24)] for _ in range(7)]
    heat_stamps=[]
    for reg in all_event_regs:
        event=all_event_by.get(reg.event_id); stamp=event.starts_at if event and event.starts_at else (reg.confirmed_at or reg.checkin_at)
        if stamp: heat_stamps.append(stamp)
    heat_stamps.extend(filter(None, (_storage_to_local(r.completed_at or r.approved_at) for r in all_qparts if r.status=="approved" and (r.completed_at or r.approved_at))))
    heat_stamps.extend(filter(None, (_storage_to_local(r.submitted_at or r.approved_at) for r in all_tparts if r.status=="approved" and (r.submitted_at or r.approved_at))))
    heat_stamps.extend(filter(None, (_storage_to_local(r.submitted_at or r.completed_at) for r in all_apps if r.status=="activity_completed" and (r.submitted_at or r.completed_at))))
    heat_stamps.extend(filter(None, (_storage_to_local(r.completed_at) for r in all_survey_responses if r.completed_at)))
    heat_stamps.extend(filter(None, (_storage_to_local(i.created_at) for i in all_ideas if i.created_at)))
    for stamp in heat_stamps: heatmap[stamp.weekday()][stamp.hour]+=1

    # Reporting 2.0 conversion funnels. Registration funnel is cohort-based:
    # only journeys started in the selected period are included, and later
    # stages are counted only when they occurred before the report cut-off.
    cutoff=min(end, generated_at + timedelta(microseconds=1))
    cutoff_utc = clock.storage_utc(clock.local_wall_to_utc(cutoff))
    journey_rows=list((await session.scalars(
        select(RegistrationJourney).where(RegistrationJourney.started_at>=start_utc, RegistrationJourney.started_at<end_utc)
    )).all())
    registration_funnel={
        "start":len(journey_rows),
        "consent":sum(1 for r in journey_rows if r.consent_at and r.consent_at < cutoff_utc),
        "profile":sum(1 for r in journey_rows if r.profile_at and r.profile_at < cutoff_utc),
        "submit":sum(1 for r in journey_rows if r.submitted_at and r.submitted_at < cutoff_utc),
        "approved":sum(1 for r in journey_rows if r.approved_at and r.approved_at < cutoff_utc),
        "first_activity":sum(1 for r in journey_rows if r.first_activity_at and r.first_activity_at < cutoff_utc),
    }
    completed_regs=[r for r in regs if r.event_id in completed_event_ids]
    event_feedback_for_period=list((await session.scalars(
        select(EventFeedback).where(EventFeedback.event_id.in_(completed_event_ids) if completed_event_ids else EventFeedback.id==-1)
    )).all())
    event_xp_rows=list((await session.scalars(
        select(XPTransaction).where(
            XPTransaction.event_id.in_(completed_event_ids) if completed_event_ids else XPTransaction.id==-1,
            XPTransaction.category=="event", XPTransaction.amount>0,
        )
    )).all())
    event_conversion={
        "registered":sum(1 for r in completed_regs if r.status != "cancelled"),
        "checkin":sum(1 for r in completed_regs if r.checkin_at is not None or r.status in {"checked_in","attended"}),
        "attended":len(attended),
        "xp":len({r.user_id for r in event_xp_rows}),
        "feedback":sum(1 for r in event_feedback_for_period if r.status=="completed"),
    }

    settlement_quality=await settlement_quality_report(session)
    data_quality={
        "settlement_duplicate_groups":int(settlement_quality.get("duplicate_count",0)),
        "settlement_noncanonical":int(settlement_quality.get("noncanonical_count",0)),
        "profiles_without_settlement":sum(1 for u in users if not canonicalize_settlement_text(u.settlement)),
        "future_attendance_anomalies":future_attendance_anomalies,
    }
    data_quality["total_issues"] = sum(int(v or 0) for v in data_quality.values())

    indicator_definitions=[
        ("Завершені події","Події вибраного періоду, для яких завершилося операційне вікно або встановлено статус «Завершено»."),
        ("Унікальні залучені","Унікальні люди, які виконали хоча б одну підтверджену дію участі у вибраному періоді; сама реєстрація профілю не рахується."),
        ("Підтверджені відвідування","Лише підтверджена присутність на фактично завершених подіях; майбутні події не збільшують показник."),
        ("Потокові показники","Дії, що відбулися всередині вибраного періоду: відвідування, XP, квести, звернення, опитування тощо."),
        ("Моментні показники","Стан системи на момент формування звіту: активні/неактивні профілі, запити на відновлення та інші моментні значення."),
        ("Конверсія реєстрації","Когорта людей, які почали реєстрацію у вибраному періоді: старт → згода → профіль → надсилання → схвалення → перша активність."),
        ("Конверсія подій","Сукупний шлях реєстрацій на події періоду: заявка → відмітка → підтверджена участь → XP → завершений відгук."),
    ]

    summary={
        "events":len(completed_events),
        "events_planned":len(report_events),
        "events_upcoming":len(upcoming_events),
        "events_in_progress":len(in_progress_events),
        "unique_participants":len(engaged_ids),
        "visits":len(attended),
        "avg_attendance":round(len(attended)/len(completed_events),1) if completed_events else 0,
        "volunteer_hours":round(event_hours+task_hours+activity_hours,1),
        "tasks_completed":len(tparts),
        "quests_completed":len(qparts),
        "activities_completed":len(apps),
        "ideas_submitted":len(ideas),
        "ideas_implemented":len(implemented),
        "requests":len(requests),
        "requests_resolved":len(resolved_requests),
        "new_participants":len(new_users),
        "xp_awarded":positive_xp,
        "opportunity_interests":len(interests),
        "surveys_published":len(surveys),
        "survey_responses":len(survey_responses),
        "badges_awarded":len(user_badges),
        "streak_freeze_days":sum(int(r.days or 0) for r in freeze_rows),
        "active_profiles":sum(1 for u in users if getattr(u,"status",None)=="active"),
        "inactive_profiles":sum(1 for u in users if getattr(u,"status",None)=="inactive"),
        "deleted_profiles":sum(1 for u in users if getattr(u,"status",None)=="deleted"),
        "deleted_permanent_profiles":sum(1 for u in users if getattr(u,"status",None)=="deleted_permanent"),
        "restoration_requests_pending":sum(1 for u in users if getattr(u,"restoration_request_status",None)=="pending"),
        "probation_profiles":sum(1 for u in users if getattr(u,"probation_until",None) and getattr(u,"status",None)=="active"),
        "restored_profiles":sum(1 for u in users if getattr(u,"restored_at",None) is not None),
        "restoration_rejected":sum(1 for u in users if getattr(u,"restoration_request_status",None)=="rejected"),
        "participation_actions":len(attended)+len(qparts)+len(tparts)+len(apps)+len(survey_responses)+len(ideas),
        "avg_xp_per_engaged":round(positive_xp/len(engaged_ids),1) if engaged_ids else 0,
        "future_attendance_anomalies":future_attendance_anomalies,
        "feedback_responses":len(feedback_rows),
        "feedback_avg_rating":feedback_avg_rating,
        "feedback_high_rating_pct":feedback_high_rating_pct,
        "feedback_useful_pct":feedback_useful_pct,
        "feedback_new_knowledge_pct":feedback_new_knowledge_pct,
        "feedback_safe_pct":feedback_safe_pct,
        "feedback_return_pct":feedback_return_pct,
        "cohort_first_visit":cohort_funnel["first_visit"],
        "cohort_returned":cohort_funnel["returned"],
        "cohort_regular":cohort_funnel["regular"],
        "cohort_ambassadors":cohort_funnel["ambassadors"],
        "retention_30_pct":retention["days30_pct"],
        "retention_90_pct":retention["days90_pct"],
        "engagement_average":engagement["average"],
        "engagement_high":engagement["high"],
    }
    snapshot_keys={"active_profiles","inactive_profiles","deleted_profiles","deleted_permanent_profiles","restoration_requests_pending","probation_profiles","restored_profiles","restoration_rejected"}
    period_summary={k:v for k,v in summary.items() if k not in snapshot_keys}
    snapshot_summary={k:summary[k] for k in snapshot_keys}
    snapshot_summary["settlement_directory_profiles"] = sum(1 for u in users if canonicalize_settlement_text(u.settlement))
    return {"label":label,"start":start,"end":end,"generated_at":generated_at,"as_of":generated_at,"timezone":"Europe/Kyiv","summary":summary,"period_summary":period_summary,"snapshot_summary":snapshot_summary,"outcomes":outcomes,"events":event_rows,"monthly":monthly,"trend":trend,"trend_granularity":trend_granularity,"trend_granularity_label":trend_granularity_label,"registration_funnel":registration_funnel,"event_conversion":event_conversion,"data_quality":data_quality,"indicator_definitions":indicator_definitions,"age":age,"gender":gender,"settlement":settlement,"vulnerability":vuln,"vulnerability_display":vuln_display,"badge_weekly":badge_weekly,"league_distribution":league_distribution,"streak_snapshot":streak_snapshot,"cohort_funnel":cohort_funnel,"retention":retention,"engagement":engagement,"heatmap":heatmap,"heatmap_days":["Пн","Вт","Ср","Чт","Пт","Сб","Нд"],"privacy_note":(
        "Категорії вразливості подаються лише агреговано. Суперадміністратор бачить точні агреговані значення; ПІБ, контакти й списки конкретних осіб не формуються."
        if reveal_sensitive_counts else
        f"Категорії вразливості подаються лише агреговано. Значення 1–{privacy_threshold - 1} приховуються як <{privacy_threshold}; ПІБ, контакти й списки конкретних осіб не формуються."
    )}
