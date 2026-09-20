from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.opportunity_utils import deadline_urgency, opportunity_sort_key
from app.model_domains import Base

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_and_new_alembic_head():
    version = read("VERSION.txt").strip()
    assert version == read("VERSION_CHECK.txt").strip()
    assert tuple(map(int, version.split("."))) >= (1, 15, 0)
    src = read("migrations/versions/20260918_0004_survey_audience.py")
    assert 'revision: str = "20260918_0004"' in src
    assert 'down_revision: Union[str, None] = "20260917_0003"' in src
    assert '"survey_audience_users"' in src
    assert len(Base.metadata.tables) >= 56


def test_surveys_can_target_users_or_event_participants():
    model = read("app/model_domains/engagement.py")
    helper = read("app/survey_audience.py")
    web = read("app/web/routes/surveys.py")
    tg = read("app/handlers/surveys.py")
    template = read("app/web/templates/surveys.html")
    assert "audience_type" in model and "audience_event_id" in model
    assert "class SurveyAudienceUser" in model
    assert 'SURVEY_AUDIENCE_TYPES = {"all", "users", "event"}' in helper
    assert "EventRegistration.status.in_(EVENT_AUDIENCE_STATUSES)" in helper
    assert "eligible_users(session, survey)" in web
    assert "survey_available_to_user" in tg
    assert 'value="users"' in template and 'value="event"' in template


def test_week_report_language_is_clear_ukrainian():
    periods = read("app/reporting/periods.py")
    template = read("app/web/templates/reports.html")
    combined = periods + template
    assert "ISO-тиждень" not in combined
    assert "понеділок–неділя" in combined
    assert "-й тиждень" in periods


def test_event_detail_has_basic_analytics():
    overview = read("app/web/event_routes/overview.py")
    template = read("app/web/templates/event_detail.html")
    for key in ("attendance_rate", "checkin_rate", "no_show_rate", "feedback_response_rate", "xp_total", "unique_views"):
        assert key in overview
    assert "Базова аналітика події" in template
    assert "Підтверджена участь" in template
    assert "Нараховано XP" in template


def test_opportunities_sort_and_three_day_urgency():
    now = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
    urgent = SimpleNamespace(active=True, deadline=datetime(2026, 9, 20, 12, 0), created_at=datetime(2026, 9, 17, 10, 0))
    later = SimpleNamespace(active=True, deadline=datetime(2026, 9, 29, 12, 0), created_at=datetime(2026, 9, 18, 8, 0))
    no_deadline = SimpleNamespace(active=True, deadline=None, created_at=datetime(2026, 9, 18, 11, 0))
    inactive = SimpleNamespace(active=False, deadline=None, created_at=datetime(2026, 9, 18, 12, 0))
    assert deadline_urgency(urgent, now)["urgent"] is True
    assert deadline_urgency(later, now)["urgent"] is False
    rows = [inactive, no_deadline, later, urgent]
    rows.sort(key=lambda item: opportunity_sort_key(item, now))
    assert rows == [urgent, later, no_deadline, inactive]
    web = read("app/web/templates/opportunity_detail.html")
    tg = read("app/handlers/participant_opportunities.py")
    nav_tg = read("app/handlers/participant_tasks.py")
    assert "У вас є остання можливість долучитись до" in web
    assert "У вас є остання можливість долучитись до" in tg
    assert "У вас є остання можливість долучитись до" in nav_tg
    assert "opportunity_sort_key" in nav_tg


def test_case_assignee_roles_are_restricted_server_side():
    src = read("app/web/routes/requests.py")
    for role in ("SUPERADMIN", "ADMIN", "COORDINATOR", "AMBASSADOR"):
        assert f"UserRole.{role}.value" in src
    assert "Відповідальним за кейс може бути лише активний" in src


def test_system_and_ambassador_badges_are_editable_without_rule_drift():
    route = read("app/web/routes/gamification.py")
    template = read("app/web/templates/badges.html")
    seed = read("app/domain_services/gamification.py")
    donations = read("app/donations.py")
    assert "_is_system_badge_rule" in route
    assert "system_badge_ids" in route and "system_badge_ids" in template
    assert "Системне правило та поріг захищені" in template
    assert "Existing system badges are intentionally not overwritten here" in seed
    assert "preserve administrator-edited" in donations
