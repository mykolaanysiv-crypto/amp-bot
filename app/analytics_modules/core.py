from __future__ import annotations

from ..time_utils import clock

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from math import ceil
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..model_domains import (
    ActivityApplication,
    Event,
    EventRegistration,
    EventFeedback,
    Idea,
    ParticipationStreak,
    QuestParticipation,
    OpportunityInterest,
    Season,
    StreakFreeze,
    SurveyResponse,
    User,
    UserBadge,
    UserStatus,
    VolunteerTask,
    VolunteerTaskParticipation,
    XPTransaction,
)
from ..profile_data import CODE_TO_LABEL, gender_label, load_vulnerabilities
from ..leagues import LEAGUES, league_for_xp, quarter_key
from ..ui_labels import label
from ..runtime_config import get_runtime_int
from ..settlements import canonicalize_settlement_text


METRIC_ORDER = [
    "new_participants",
    "cohort_funnel",
    "retention",
    "engagement_score",
    "activity_heatmap",
    "activity",
    "visits",
    "avg_attendance",
    "event_outcomes",
    "volunteer_hours",
    "age",
    "gender",
    "settlement",
    "xp_sources",
    "ideas",
    "surveys_weekly",
    "badges_weekly",
    "leagues",
    "streaks",
    "vulnerability",
    "lifecycle",
    "restoration",
    "participation_mix",
]

METRIC_META: dict[str, dict[str, str]] = {
    "new_participants": {
        "title": "Нові учасники за місяць",
        "short": "Нові учасники",
        "icon": "👥",
        "kind": "line",
        "description": "Кількість нових реєстрацій у системі за останні 12 місяців.",
    },
    "cohort_funnel": {
        "title": "Воронка залучення за когортами",
        "short": "Когорта / повернення",
        "icon": "👥",
        "kind": "bar",
        "description": "Шлях учасника: зареєструвався → відвідав хоча б одну подію → повернувся → став регулярним → став АМПасадором. Регулярний = щонайменше 3 підтверджені відвідування у 3 різні календарні тижні.",
    },
    "retention": {
        "title": "Повернення після першого відвідування",
        "short": "Повернення 30/90",
        "icon": "🔁",
        "kind": "bar",
        "description": "Частка учасників, які після першого підтвердженого відвідування прийшли на іншу подію протягом 30 або 90 днів.",
    },
    "engagement_score": {
        "title": "Індекс залученості",
        "short": "Індекс залученості",
        "icon": "📈",
        "kind": "bar",
        "description": "Внутрішній індекс 0–100 для аналітики. Враховує регулярність, події, волонтерські години, ідеї, опитування та квести; учаснику автоматично не показується.",
    },
    "activity_heatmap": {
        "title": "Теплова карта активності",
        "short": "Теплова карта",
        "icon": "🔥",
        "kind": "heatmap",
        "description": "Коли молодь проявляє підтверджену активність: день тижня × година. Допомагає планувати час майбутніх подій.",
    },
    "activity": {
        "title": "Активність учасників за 30/90 днів",
        "short": "Активність 30/90",
        "icon": "⚡",
        "kind": "bar",
        "description": "Активні профілі визначаються за останньою взаємодією з Telegram-ботом. Показник 30 днів входить до показника 90 днів.",
    },
    "visits": {
        "title": "Відвідування за місяць",
        "short": "Відвідування",
        "icon": "📅",
        "kind": "line",
        "description": "Підтверджені відвідування подій за останні 12 місяців (статус «відвідано»).",
    },
    "avg_attendance": {
        "title": "Відвідуваність останніх подій",
        "short": "Середня відвідуваність",
        "icon": "📈",
        "kind": "bar",
        "description": "Кількість підтверджених відвідувачів останніх проведених подій. Скасовані події не враховуються.",
    },
    "event_outcomes": {
        "title": "Зворотний зв’язок та результати після подій",
        "short": "Вплив / зворотний зв’язок",
        "icon": "⭐",
        "kind": "bar",
        "description": "Агреговані відповіді завершених feedback-анкет після подій: висока оцінка, корисність, нові знання, відчуття безпеки та готовність повернутися.",
    },
    "volunteer_hours": {
        "title": "Волонтерські години за джерелами",
        "short": "Волонтерські години",
        "icon": "⏱",
        "kind": "bar",
        "description": "Підтверджені години з подій, волонтерських задач та активностей. Загальний баланс годин береться з профілів учасників.",
    },
    "age": {
        "title": "Розподіл учасників за віком",
        "short": "Вік",
        "icon": "🎂",
        "kind": "bar",
        "description": "Агрегований віковий розподіл зареєстрованих учасників станом на сьогодні.",
    },
    "gender": {
        "title": "Розподіл учасників за статтю",
        "short": "Стать",
        "icon": "◉",
        "kind": "doughnut",
        "description": "Агрегований розподіл за значенням, зазначеним учасниками під час реєстрації.",
    },
    "settlement": {
        "title": "Розподіл за населеними пунктами",
        "short": "Населені пункти",
        "icon": "📍",
        "kind": "bar",
        "description": "Агрегована кількість зареєстрованих учасників за населеними пунктами.",
    },
    "xp_sources": {
        "title": "Джерела нарахування XP",
        "short": "Джерела XP",
        "icon": "✨",
        "kind": "bar",
        "description": "Сума позитивних нарахувань XP за категоріями. Списання та нульові транзакції не враховуються.",
    },
    "ideas": {
        "title": "Ідеї учасників за статусами",
        "short": "Реалізовані ідеї",
        "icon": "💡",
        "kind": "bar",
        "description": "Кількість ідей за етапами роботи. Окремо виділяється кількість реалізованих ідей.",
    },
    "surveys_weekly": {
        "title": "Проходження опитувань по тижнях",
        "short": "Опитування",
        "icon": "📋",
        "kind": "line",
        "description": "Кількість завершених опитувань учасниками за останні 12 календарних тижнів.",
    },
    "badges_weekly": {
        "title": "Отримані бейджі по тижнях",
        "short": "Бейджі по тижнях",
        "icon": "🏅",
        "kind": "line",
        "description": "Кількість бейджів, виданих учасникам за кожен із останніх 12 календарних тижнів.",
    },
    "leagues": {
        "title": "Розподіл учасників за лігами",
        "short": "Ліги",
        "icon": "🏆",
        "kind": "bar",
        "description": "Поточний розподіл активних учасників за сезонними лігами на основі XP активного сезону.",
    },
    "streaks": {
        "title": "Серії участі",
        "short": "Серії",
        "icon": "🔥",
        "kind": "bar",
        "description": "Поточна кількість учасників із тижневою серією, суперсерією, відновлюваною суперсерією та активною заморозкою.",
    },
    "lifecycle": {
        "title": "Статуси життєвого циклу учасників",
        "short": "Статуси профілів",
        "icon": "👤",
        "kind": "bar",
        "description": "Розподіл профілів: очікує підтвердження, активні, неактивні, заблоковані, видалені та остаточно видалені.",
    },
    "restoration": {
        "title": "Відновлення та випробувальний строк",
        "short": "Відновлення",
        "icon": "♻️",
        "kind": "bar",
        "description": "Стан автоматичного lifecycle після видалення: запити на відновлення, відновлені профілі, активний probation та остаточне закриття доступу.",
    },
    "participation_mix": {
        "title": "Структура участі",
        "short": "Структура участі",
        "icon": "🧭",
        "kind": "bar",
        "description": "Сумарна кількість підтверджених дій у ключових механіках системи.",
    },
    "vulnerability": {
        "title": "Категорії вразливості — агреговано",
        "short": "Категорії вразливості",
        "icon": "🧩",
        "kind": "bar",
        "description": "Тільки агреговані кількості без ПІБ, контактів або переліку конкретних учасників. Одна людина може входити до кількох категорій.",
    },
}

IDEA_STATUS_LABELS = {
    "new": "Нова",
    "review": "На розгляді",
    "shortlisted": "Відібрана",
    "approved": "Схвалена",
    "in_progress": "У реалізації",
    "paused": "Призупинена",
    "implemented": "Реалізована",
    "rejected": "Відхилена",
    "archived": "Архівна",
}


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _week_label(value: date) -> str:
    return value.strftime("%d.%m")


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, months: int) -> date:
    idx = value.year * 12 + (value.month - 1) + months
    return date(idx // 12, idx % 12 + 1, 1)


def _month_key(value: datetime | date | None) -> str | None:
    if not value:
        return None
    return f"{value.year:04d}-{value.month:02d}"


def _month_label(value: date) -> str:
    months = ["січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"]
    return f"{months[value.month - 1]} {str(value.year)[2:]}"


def _age_on(birth_date: date | None, today: date) -> int | None:
    if not birth_date:
        return None
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _metric(key: str, labels: list[str], values: list[float | int], *, rows: list[dict[str, Any]] | None = None, value_label: str = "Кількість") -> dict[str, Any]:
    meta = METRIC_META[key]
    return {
        "key": key,
        "title": meta["title"],
        "short": meta["short"],
        "icon": meta["icon"],
        "kind": meta["kind"],
        "description": meta["description"],
        "labels": labels,
        "values": values,
        "rows": rows or [{"label": lab, "value": val} for lab, val in zip(labels, values)],
        "value_label": value_label,
    }


async def build_analytics(session: AsyncSession, *, now: datetime | None = None, reveal_sensitive_counts: bool = False) -> dict[str, Any]:
    privacy_threshold = await get_runtime_int(session, "privacy.suppression_threshold")
    """Build live, aggregate-only analytics from the existing database.

    No participant names, contacts, Telegram IDs or row-level vulnerability data
    are returned. Superadmins may request unsuppressed aggregate counts for small
    vulnerability groups; all other viewers receive privacy-threshold suppression.
    """
    now = now or clock.storage_utc()
    today = now.date()
    active_users = (await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value))).all()
    all_users = (await session.scalars(select(User))).all()
    events = (await session.scalars(select(Event))).all()
    regs = (await session.scalars(select(EventRegistration))).all()
    txs = (await session.scalars(select(XPTransaction))).all()
    ideas = (await session.scalars(select(Idea))).all()
    tasks = (await session.scalars(select(VolunteerTask))).all()
    task_parts = (await session.scalars(select(VolunteerTaskParticipation))).all()
    quest_parts = (await session.scalars(select(QuestParticipation))).all()
    activity_apps = (await session.scalars(select(ActivityApplication))).all()
    opportunity_interests = (await session.scalars(select(OpportunityInterest))).all()
    survey_responses = (await session.scalars(select(SurveyResponse))).all()
    feedback_rows = (await session.scalars(select(EventFeedback).where(EventFeedback.status == "completed"))).all()
    user_badges = (await session.scalars(select(UserBadge))).all()
    streak_rows = (await session.scalars(select(ParticipationStreak))).all()
    freezes = (await session.scalars(select(StreakFreeze))).all()
    active_season = await session.scalar(select(Season).where(Season.active == True).order_by(Season.starts_at.desc()))  # noqa: E712

    event_by_id = {e.id: e for e in events}
    task_by_id = {t.id: t for t in tasks}

    month_starts = [_shift_month(_month_start(today), offset) for offset in range(-11, 1)]
    month_keys = [f"{m.year:04d}-{m.month:02d}" for m in month_starts]
    month_labels = [_month_label(m) for m in month_starts]

    registrations_by_month = Counter(_month_key(u.created_at) for u in all_users if u.created_at)
    new_metric = _metric(
        "new_participants",
        month_labels,
        [registrations_by_month.get(k, 0) for k in month_keys],
        value_label="Нові реєстрації",
    )

    cutoff30 = now - timedelta(days=30)
    cutoff90 = now - timedelta(days=90)
    active30 = sum(1 for u in active_users if (u.last_activity_at or u.created_at) >= cutoff30)
    active90 = sum(1 for u in active_users if (u.last_activity_at or u.created_at) >= cutoff90)
    inactive90 = max(0, len(active_users) - active90)
    activity_metric = _metric(
        "activity",
        ["Активні ≤30 днів", "Активні ≤90 днів", "Неактивні >90 днів"],
        [active30, active90, inactive90],
        value_label="Учасники",
    )

    checkin_close_minutes = await get_runtime_int(session, "events.checkin_close_after_minutes")
    event_reference_utc = clock.now_utc()
    completed_event_ids = {
        e.id for e in events
        if e.status == "completed"
        or (e.starts_at and clock.event_utc(e.starts_at) + timedelta(minutes=checkin_close_minutes) < event_reference_utc)
    }
    # Legacy/manual bad rows from future events must never pollute attendance analytics.
    attended_regs = [r for r in regs if r.status == "attended" and r.event_id in completed_event_ids]

    # v1.9.1 — Advanced Analytics. Cohort stages are intentionally aggregate-only.
    participant_roles = {"participant", "ambassador"}
    cohort_users = [u for u in all_users if (u.role or "participant") in participant_roles]
    cohort_user_ids = {u.id for u in cohort_users}
    attended_dates_by_user: dict[int, list[datetime]] = defaultdict(list)
    for reg in attended_regs:
        event = event_by_id.get(reg.event_id)
        stamp = event.starts_at if event and event.starts_at else (reg.confirmed_at or reg.checkin_at)
        if stamp and reg.user_id in cohort_user_ids:
            attended_dates_by_user[reg.user_id].append(stamp)
    for values in attended_dates_by_user.values():
        values.sort()

    first_visit_ids = {uid for uid, visits in attended_dates_by_user.items() if visits}
    returned_ids = {uid for uid, visits in attended_dates_by_user.items() if len(visits) >= 2}
    regular_ids = {
        uid for uid, visits in attended_dates_by_user.items()
        if len(visits) >= 3 and len({(v.isocalendar().year, v.isocalendar().week) for v in visits}) >= 3
    }
    ambassador_ids = {u.id for u in cohort_users if u.role == "ambassador"}
    regular_ambassadors = regular_ids & ambassador_ids
    cohort_values = [len(cohort_users), len(first_visit_ids), len(returned_ids), len(regular_ids), len(regular_ambassadors)]
    cohort_labels = ["Зареєструвалися", "Прийшли 1 раз", "Повернулися", "Стали регулярними", "Стали АМПасадорами"]
    cohort_rows = []
    previous = None
    for stage, value in zip(cohort_labels, cohort_values):
        conversion = 100.0 if previous is None else (round(value / previous * 100, 1) if previous else 0.0)
        cohort_rows.append({"label": stage, "value": value, "secondary": ("Базова когорта" if previous is None else f"{conversion:g}% від попереднього етапу")})
        previous = value
    cohort_metric = _metric("cohort_funnel", cohort_labels, cohort_values, rows=cohort_rows, value_label="Учасники")

    retention_30_ids: set[int] = set()
    retention_90_ids: set[int] = set()
    for uid, visits in attended_dates_by_user.items():
        if len(visits) < 2:
            continue
        first = visits[0]
        if any(first < nxt <= first + timedelta(days=30) for nxt in visits[1:]):
            retention_30_ids.add(uid)
        if any(first < nxt <= first + timedelta(days=90) for nxt in visits[1:]):
            retention_90_ids.add(uid)
    retention_base = len(first_visit_ids)
    retention_30_pct = round(len(retention_30_ids) / retention_base * 100, 1) if retention_base else 0.0
    retention_90_pct = round(len(retention_90_ids) / retention_base * 100, 1) if retention_base else 0.0
    retention_metric = _metric(
        "retention",
        ["Повернулися ≤30 днів", "Повернулися ≤90 днів"],
        [retention_30_pct, retention_90_pct],
        rows=[
            {"label": "Повернулися ≤30 днів", "value": retention_30_pct, "secondary": f"{len(retention_30_ids)} з {retention_base} учасників"},
            {"label": "Повернулися ≤90 днів", "value": retention_90_pct, "secondary": f"{len(retention_90_ids)} з {retention_base} учасників"},
        ],
        value_label="% учасників",
    )

    # Індекс залученості is a private aggregate index, not another XP balance.
    event_count_by_user = Counter(r.user_id for r in attended_regs)
    quest_count_by_user = Counter(r.user_id for r in quest_parts if r.status == "approved")
    survey_count_by_user = Counter(r.user_id for r in survey_responses)
    idea_count_by_user = Counter(i.user_id for i in ideas)
    streak_by_user = {row.user_id: int(row.weekly_streak or 0) for row in streak_rows}
    engagement_scores: dict[int, int] = {}
    for u in cohort_users:
        score = (
            min(streak_by_user.get(u.id, 0) / 4, 1) * 20
            + min(event_count_by_user.get(u.id, 0) / 6, 1) * 25
            + min(float(u.volunteer_hours or 0) / 10, 1) * 20
            + min(idea_count_by_user.get(u.id, 0) / 2, 1) * 10
            + min(survey_count_by_user.get(u.id, 0) / 4, 1) * 10
            + min(quest_count_by_user.get(u.id, 0) / 4, 1) * 15
        )
        engagement_scores[u.id] = int(round(score))
    engagement_average = round(sum(engagement_scores.values()) / len(engagement_scores), 1) if engagement_scores else 0.0
    engagement_bands = [
        ("0–24 • низька", 0, 24),
        ("25–49 • базова", 25, 49),
        ("50–74 • висока", 50, 74),
        ("75–100 • дуже висока", 75, 100),
    ]
    engagement_values = [sum(1 for value in engagement_scores.values() if low <= value <= high) for _, low, high in engagement_bands]
    engagement_metric = _metric(
        "engagement_score",
        [name for name, _, _ in engagement_bands],
        engagement_values,
        rows=[
            {"label": name, "value": count, "secondary": f"Середній індекс: {engagement_average:g}/100" if idx == 0 else ""}
            for idx, ((name, _, _), count) in enumerate(zip(engagement_bands, engagement_values))
        ],
        value_label="Учасники",
    )

    # Теплова карта: confirmed/meaningful participant actions by weekday and hour.
    heatmap_matrix = [[0 for _ in range(24)] for _ in range(7)]
    heatmap_stamps: list[datetime] = []
    for reg in attended_regs:
        event = event_by_id.get(reg.event_id)
        stamp = event.starts_at if event and event.starts_at else (reg.confirmed_at or reg.checkin_at)
        if stamp:
            heatmap_stamps.append(stamp)
    heatmap_stamps.extend(r.completed_at or r.approved_at for r in quest_parts if (r.completed_at or r.approved_at) and r.status == "approved")
    heatmap_stamps.extend(r.submitted_at or r.approved_at for r in task_parts if (r.submitted_at or r.approved_at) and r.status == "approved")
    heatmap_stamps.extend(r.submitted_at or r.completed_at for r in activity_apps if (r.submitted_at or r.completed_at) and r.status == "activity_completed")
    heatmap_stamps.extend(r.completed_at for r in survey_responses if r.completed_at)
    heatmap_stamps.extend(i.created_at for i in ideas if i.created_at)
    for stamp in heatmap_stamps:
        heatmap_matrix[stamp.weekday()][stamp.hour] += 1
    heatmap_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    heatmap_hours = [f"{hour:02d}:00" for hour in range(24)]
    heatmap_metric = _metric(
        "activity_heatmap",
        heatmap_hours,
        [sum(heatmap_matrix[d][h] for d in range(7)) for h in range(24)],
        rows=[{"label": heatmap_days[d], "value": sum(heatmap_matrix[d]), "secondary": "Сумарні дії за день тижня"} for d in range(7)],
        value_label="Дії",
    )
    heatmap_metric["matrix"] = heatmap_matrix
    heatmap_metric["days"] = heatmap_days
    heatmap_metric["hours"] = heatmap_hours

    visits_by_month = Counter(_month_key(r.confirmed_at or r.checkin_at) for r in attended_regs if (r.confirmed_at or r.checkin_at))
    visits_metric = _metric(
        "visits",
        month_labels,
        [visits_by_month.get(k, 0) for k in month_keys],
        value_label="Відвідування",
    )

    attendance_by_event = Counter(r.event_id for r in attended_regs)
    past_events = [e for e in events if e.starts_at <= now and e.status not in {"cancelled", "draft"} and not e.cancelled_at]
    past_events.sort(key=lambda e: e.starts_at, reverse=True)
    recent_events = list(reversed(past_events[:12]))
    attendance_rows = [
        {
            "label": e.title,
            "value": attendance_by_event.get(e.id, 0),
            "secondary": e.starts_at.strftime("%d.%m.%Y"),
        }
        for e in recent_events
    ]
    avg_attendance = round(sum(attendance_by_event.get(e.id, 0) for e in past_events) / len(past_events), 1) if past_events else 0.0
    avg_metric = _metric(
        "avg_attendance",
        [r["label"] for r in attendance_rows],
        [r["value"] for r in attendance_rows],
        rows=attendance_rows,
        value_label="Відвідувачі",
    )

    def _pct_true(rows, attr: str) -> float:
        values = [getattr(row, attr, None) for row in rows if getattr(row, attr, None) is not None]
        return round((sum(1 for value in values if value) / len(values) * 100), 1) if values else 0.0

    rating_values = [int(row.rating) for row in feedback_rows if row.rating is not None]
    feedback_avg_rating = round(sum(rating_values) / len(rating_values), 2) if rating_values else 0.0
    feedback_high_rating_pct = round(sum(1 for value in rating_values if value >= 4) / len(rating_values) * 100, 1) if rating_values else 0.0
    feedback_useful_pct = _pct_true(feedback_rows, "useful")
    feedback_knowledge_pct = _pct_true(feedback_rows, "new_knowledge")
    feedback_safe_pct = _pct_true(feedback_rows, "felt_safe")
    feedback_return_pct = _pct_true(feedback_rows, "would_return")
    feedback_metric = _metric(
        "event_outcomes",
        ["Висока оцінка 4–5", "Було корисно", "Нові знання", "Почувалися безпечно", "Хочуть прийти ще"],
        [feedback_high_rating_pct, feedback_useful_pct, feedback_knowledge_pct, feedback_safe_pct, feedback_return_pct],
        rows=[
            {"label": "Висока оцінка 4–5", "value": feedback_high_rating_pct, "secondary": f"Середня оцінка {feedback_avg_rating:g}/5"},
            {"label": "Було корисно", "value": feedback_useful_pct},
            {"label": "Нові знання", "value": feedback_knowledge_pct},
            {"label": "Почувалися безпечно", "value": feedback_safe_pct},
            {"label": "Хочуть прийти ще", "value": feedback_return_pct},
        ],
        value_label="% відповідей",
    )

    event_hours = sum(float(event_by_id[r.event_id].volunteer_hours or 0) for r in attended_regs if r.event_id in event_by_id)
    task_hours = sum(float(task_by_id[p.task_id].hours_reward or 0) for p in task_parts if p.status == "approved" and p.task_id in task_by_id)
    activity_hours = sum(float(a.hours_reward or 0) for a in activity_apps if a.status == "activity_completed")
    current_volunteer_balance = round(sum(float(u.volunteer_hours or 0) for u in all_users), 1)
    reconstructed_hours = round(event_hours + task_hours + activity_hours, 1)
    other_hours = round(max(0.0, current_volunteer_balance - reconstructed_hours), 1)
    volunteer_labels = ["Події", "Волонтерські задачі", "Активності"]
    volunteer_values = [round(event_hours, 1), round(task_hours, 1), round(activity_hours, 1)]
    if other_hours > 0:
        volunteer_labels.append("Інші / історичні нарахування")
        volunteer_values.append(other_hours)
    volunteer_metric = _metric(
        "volunteer_hours",
        volunteer_labels,
        volunteer_values,
        value_label="Години",
    )

    age_bands = [
        ("До 14", lambda a: a is not None and a < 14),
        ("14–17", lambda a: a is not None and 14 <= a <= 17),
        ("18–21", lambda a: a is not None and 18 <= a <= 21),
        ("22–25", lambda a: a is not None and 22 <= a <= 25),
        ("26–30", lambda a: a is not None and 26 <= a <= 30),
        ("31–35", lambda a: a is not None and 31 <= a <= 35),
        ("36+", lambda a: a is not None and a >= 36),
        ("Не зазначено", lambda a: a is None),
    ]
    ages = [_age_on(u.birth_date, today) for u in all_users]
    age_metric = _metric(
        "age",
        [name for name, _ in age_bands],
        [sum(1 for age in ages if predicate(age)) for _, predicate in age_bands],
        value_label="Учасники",
    )

    gender_counts = Counter(gender_label(u.gender) for u in all_users)
    gender_items = sorted(gender_counts.items(), key=lambda x: (-x[1], x[0]))
    gender_metric = _metric("gender", [x[0] for x in gender_items], [x[1] for x in gender_items], value_label="Учасники")

    settlement_counts = Counter(canonicalize_settlement_text(u.settlement) or "Не зазначено" for u in all_users)
    settlement_items = sorted(settlement_counts.items(), key=lambda x: (-x[1], x[0]))
    settlement_metric = _metric("settlement", [x[0] for x in settlement_items], [x[1] for x in settlement_items], value_label="Учасники")

    xp_counts: dict[str, int] = defaultdict(int)
    xp_transactions_count: dict[str, int] = defaultdict(int)
    for tx in txs:
        if int(tx.amount or 0) <= 0:
            continue
        source = label(tx.category or "other")
        xp_counts[source] += int(tx.amount or 0)
        xp_transactions_count[source] += 1
    xp_items = sorted(xp_counts.items(), key=lambda x: (-x[1], x[0]))
    xp_rows = [
        {"label": source, "value": amount, "secondary": f"{xp_transactions_count[source]} нарахувань"}
        for source, amount in xp_items
    ]
    xp_metric = _metric(
        "xp_sources",
        [x[0] for x in xp_items],
        [x[1] for x in xp_items],
        rows=xp_rows,
        value_label="XP",
    )

    idea_counts = Counter(i.status or "new" for i in ideas)
    idea_keys = ["new", "review", "shortlisted", "approved", "in_progress", "paused", "implemented", "rejected", "archived"]
    idea_labels = [IDEA_STATUS_LABELS[k] for k in idea_keys]
    ideas_metric = _metric(
        "ideas",
        idea_labels,
        [idea_counts.get(k, 0) for k in idea_keys],
        value_label="Ідеї",
    )

    vuln_counts: Counter[str] = Counter()
    withheld = 0
    for u in all_users:
        codes, _ = load_vulnerabilities(u.vulnerability_categories)
        if not codes:
            withheld += 1
            continue
        for code in codes:
            if code == "other":
                vuln_counts["Інша категорія"] += 1
            else:
                vuln_counts[CODE_TO_LABEL.get(code, code)] += 1
    if withheld:
        vuln_counts["Не зазначено / не бажає повідомляти"] += withheld
    vuln_items = sorted(vuln_counts.items(), key=lambda x: (-x[1], x[0]))
    # Privacy threshold: small sensitive groups must not be disclosed literally.
    # The chart receives 0 for suppressed cells and all human-readable exports
    # show “<5” instead of the exact 1–4 value.
    vuln_rows = []
    vuln_values = []
    for name, count in vuln_items:
        suppressed = (not reveal_sensitive_counts) and 0 < int(count) < privacy_threshold
        vuln_values.append(0 if suppressed else int(count))
        vuln_rows.append({
            "label": name,
            "value": 0 if suppressed else int(count),
            "display_value": f"<{privacy_threshold}" if suppressed else str(int(count)),
            "secondary": "Мала група — точне значення приховано" if suppressed else "",
            "suppressed": suppressed,
        })
    vulnerability_metric = _metric(
        "vulnerability",
        [x[0] for x in vuln_items],
        vuln_values,
        rows=vuln_rows,
        value_label="Учасники",
    )

    current_week = _week_start(today)
    week_starts = [current_week - timedelta(days=7 * offset) for offset in range(11, -1, -1)]
    week_labels = [_week_label(w) for w in week_starts]
    survey_week_counts = Counter(_week_start(r.completed_at.date()) for r in survey_responses if r.completed_at)
    survey_metric = _metric(
        "surveys_weekly", week_labels, [survey_week_counts.get(w, 0) for w in week_starts],
        value_label="Проходження",
    )
    badge_week_counts = Counter(_week_start(r.awarded_at.date()) for r in user_badges if r.awarded_at)
    badges_metric = _metric(
        "badges_weekly", week_labels, [badge_week_counts.get(w, 0) for w in week_starts],
        value_label="Отримані бейджі",
    )

    league_counts_map = {lg.code: 0 for lg in LEAGUES}
    if active_season:
        season_xp_by_user: Counter[int] = Counter()
        for tx in txs:
            if tx.season_id == active_season.id:
                season_xp_by_user[tx.user_id] += int(tx.amount or 0)
        for u in active_users:
            lg = league_for_xp(season_xp_by_user.get(u.id, 0))
            league_counts_map[lg.code] += 1
    leagues_metric = _metric(
        "leagues", [f"{lg.icon} {lg.title}" for lg in LEAGUES],
        [league_counts_map[lg.code] for lg in LEAGUES], value_label="Учасники",
    )

    now_frozen_ids = {f.user_id for f in freezes if f.starts_at <= now < f.ends_at}
    streak_metric = _metric(
        "streaks",
        ["Тижнева серія", "Суперсерія", "Можна відновити", "Заморожено зараз"],
        [
            sum(1 for row in streak_rows if int(row.weekly_streak or 0) > 0),
            sum(1 for row in streak_rows if int(row.event_streak or 0) > 0),
            sum(1 for row in streak_rows if int(row.recoverable_event_streak or 0) > 0),
            len(now_frozen_ids),
        ],
        value_label="Учасники",
    )
    current_q = quarter_key(now)
    freeze_days_quarter = sum(int(f.days or 0) for f in freezes if f.quarter_key == current_q)

    lifecycle_keys=["pending","active","inactive","blocked","deleted","deleted_permanent"]
    lifecycle_metric=_metric(
        "lifecycle",
        [label(k) for k in lifecycle_keys],
        [sum(1 for u in all_users if u.status==k) for k in lifecycle_keys],
        value_label="Профілі",
    )
    restoration_metric=_metric(
        "restoration",
        ["Видалено", "Запит очікує", "Відновлено", "На probation", "Без відновлення"],
        [
            sum(1 for u in all_users if u.status=="deleted"),
            sum(1 for u in all_users if getattr(u,"restoration_request_status",None)=="pending"),
            sum(1 for u in all_users if getattr(u,"restored_at",None) is not None),
            sum(1 for u in all_users if getattr(u,"probation_until",None) and u.status=="active"),
            sum(1 for u in all_users if u.status=="deleted_permanent"),
        ],
        value_label="Профілі",
    )
    participation_metric=_metric(
        "participation_mix",
        ["Події","Квести","Волонтерські задачі","Активності","Опитування","Ідеї","Інтерес до можливостей"],
        [
            len(attended_regs),
            sum(1 for r in quest_parts if r.status=="approved"),
            sum(1 for r in task_parts if r.status=="approved"),
            sum(1 for r in activity_apps if r.status=="activity_completed"),
            len(survey_responses),
            len(ideas),
            sum(1 for r in opportunity_interests if r.status=="interested"),
        ],
        value_label="Дії",
    )

    metrics = {
        item["key"]: item
        for item in [
            new_metric,
            cohort_metric,
            retention_metric,
            engagement_metric,
            heatmap_metric,
            activity_metric,
            visits_metric,
            avg_metric,
            feedback_metric,
            volunteer_metric,
            age_metric,
            gender_metric,
            settlement_metric,
            xp_metric,
            ideas_metric,
            survey_metric,
            badges_metric,
            leagues_metric,
            streak_metric,
            vulnerability_metric,
            lifecycle_metric,
            restoration_metric,
            participation_metric,
        ]
    }

    current_month_key = f"{today.year:04d}-{today.month:02d}"
    summary = {
        "participants": len(all_users),
        "new_this_month": registrations_by_month.get(current_month_key, 0),
        "cohort_registered": len(cohort_users),
        "cohort_first_visit": len(first_visit_ids),
        "cohort_returned": len(returned_ids),
        "cohort_regular": len(regular_ids),
        "cohort_ambassadors": len(regular_ambassadors),
        "retention_30_count": len(retention_30_ids),
        "retention_30_pct": retention_30_pct,
        "retention_90_count": len(retention_90_ids),
        "retention_90_pct": retention_90_pct,
        "engagement_average": engagement_average,
        "engagement_high": sum(1 for value in engagement_scores.values() if value >= 75),
        "active30": active30,
        "active90": active90,
        "visits": len(attended_regs),
        "avg_attendance": avg_attendance,
        "feedback_responses": len(feedback_rows),
        "feedback_avg_rating": feedback_avg_rating,
        "feedback_high_rating_pct": feedback_high_rating_pct,
        "feedback_useful_pct": feedback_useful_pct,
        "feedback_new_knowledge_pct": feedback_knowledge_pct,
        "feedback_safe_pct": feedback_safe_pct,
        "feedback_return_pct": feedback_return_pct,
        "volunteer_hours": current_volunteer_balance,
        "implemented_ideas": idea_counts.get("implemented", 0),
        "total_xp_awarded": sum(int(tx.amount or 0) for tx in txs if int(tx.amount or 0) > 0),
        "survey_responses_12w": sum(survey_week_counts.get(w, 0) for w in week_starts),
        "badges_12w": sum(badge_week_counts.get(w, 0) for w in week_starts),
        "frozen_streaks": len(now_frozen_ids),
        "freeze_days_quarter": freeze_days_quarter,
        "deleted_profiles": sum(1 for u in all_users if u.status=="deleted"),
        "deleted_permanent": sum(1 for u in all_users if u.status=="deleted_permanent"),
        "restoration_pending": sum(1 for u in all_users if getattr(u,"restoration_request_status",None)=="pending"),
        "probation_active": sum(1 for u in all_users if getattr(u,"probation_until",None) and u.status=="active"),
        "restored_profiles": sum(1 for u in all_users if getattr(u,"restored_at",None) is not None),
        "restoration_rejected": sum(1 for u in all_users if getattr(u,"restoration_request_status",None)=="rejected"),
        "active30_share": round((active30 / len(active_users) * 100), 1) if active_users else 0,
        "confirmed_participation_actions": len(attended_regs)+sum(1 for r in quest_parts if r.status=="approved")+sum(1 for r in task_parts if r.status=="approved")+sum(1 for r in activity_apps if r.status=="activity_completed")+len(survey_responses),
    }
    return {
        "generated_at": now,
        "summary": summary,
        "metrics": metrics,
        "metric_order": METRIC_ORDER,
        "privacy_note": (
            "Режим суперадміністратора: точні агреговані значення, включно з малими групами, показуються без приховування. ПІБ, контакти та списки конкретних учасників у цій аналітиці не формуються."
            if reveal_sensitive_counts else
            f"Аналітика є агрегованою. Для категорій вразливості значення 1–{privacy_threshold - 1} приховуються як <{privacy_threshold}; ПІБ, контакти та списки конкретних учасників не формуються."
        ),
        "sensitive_counts_visible": bool(reveal_sensitive_counts),
    }
