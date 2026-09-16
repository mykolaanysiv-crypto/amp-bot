from pathlib import Path

from app.models import Base, User, UserStatus
from tests.source_layout import analytics_source, event_routes_source, main_source, reports_source, start_source

ROOT = Path(__file__).resolve().parents[1]


def test_v181_statuses_and_schema_fields():
    assert UserStatus.DELETED.value == "deleted"
    assert UserStatus.DELETED_PERMANENT.value == "deleted_permanent"
    cols = {c.name for c in User.__table__.columns}
    for name in {
        "deleted_at", "deletion_reason", "restoration_requested_at",
        "restoration_request_status", "restoration_answers_json",
        "restored_at", "probation_started_at", "probation_until",
        "permanent_deleted_at",
    }:
        assert name in cols
    assert len(Base.metadata.tables) >= 53


def test_deleted_statuses_are_not_manual_web_status_options():
    route = (ROOT / "app/web/routes/users.py").read_text(encoding="utf-8")
    assert "allowed_statuses={UserStatus.PENDING.value,UserStatus.ACTIVE.value,UserStatus.INACTIVE.value}" in route
    assert "workflow відновлення" in route
    template = (ROOT / "app/web/templates/user_detail.html").read_text(encoding="utf-8")
    assert "автоматичний статус" in template


def test_restoration_flow_and_probation_exist():
    start = start_source()
    main = main_source()
    assert 'callback_data="restore:start"' in start
    assert "RestorationState.reason" in start
    assert "14-денний випробувальний строк" in start
    assert 'restored.status = "deleted_permanent"' in main
    assert "restoration_probation_passed" in main


def test_participant_360_and_health_label():
    template = (ROOT / "app/web/templates/user_detail.html").read_text(encoding="utf-8")
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "Participant 360" in template
    for tab in ["Огляд", "Активність", "XP", "Події", "Волонтерство", "Ідеї", "Опитування", "Бейджі", "Документи"]:
        assert tab in template
    assert "🩺 Стан системи" in base


def test_auto_notifications_for_new_content_are_wired():
    text = "\n".join([
        event_routes_source(),
        (ROOT / "app/web/routes/quests.py").read_text(encoding="utf-8"),
        (ROOT / "app/web/routes/tasks.py").read_text(encoding="utf-8"),
        (ROOT / "app/web/routes/activities.py").read_text(encoding="utf-8"),
        (ROOT / "app/web/routes/opportunities.py").read_text(encoding="utf-8"),
        (ROOT / "app/web/routes/surveys.py").read_text(encoding="utf-8"),
    ])
    for code in ["event_created", "quest_created", "task_created", "activity_created", "survey_published"]:
        assert code in text
    # Since v1.9.2 opportunities are personalized instead of mass-broadcast.
    opportunities = (ROOT / "app/web/routes/opportunities.py").read_text(encoding="utf-8")
    matching = (ROOT / "app/opportunity_matching.py").read_text(encoding="utf-8")
    assert "refresh_matches_for_opportunity" in opportunities
    assert 'source="opportunity_match"' in matching


def test_analytics_has_v181_lifecycle_metrics():
    analytics = analytics_source()
    reports = reports_source()
    assert '"lifecycle"' in analytics
    assert '"participation_mix"' in analytics
    assert '"restoration"' in analytics
    assert '"restoration_pending"' in analytics
    assert '"deleted_permanent_profiles"' in reports
    assert '"avg_xp_per_engaged"' in reports
    assert '"restored_profiles"' in reports
