from pathlib import Path

from app.models import Base, ContentView

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v11217_version_and_schema():
    version = _read("VERSION.txt").strip()
    assert _read("VERSION_CHECK.txt").strip() == version
    assert tuple(map(int, version.split("."))) >= (1, 12, 1, 7)
    assert "content_views" in Base.metadata.tables
    assert len(Base.metadata.tables) >= 54
    table = ContentView.__table__
    assert {"entity_type", "entity_id", "user_id", "tg_id", "view_count", "first_viewed_at", "last_viewed_at"} <= set(table.columns.keys())
    uniques = [c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({col.name for col in c.columns} == {"entity_type", "entity_id", "tg_id"} for c in uniques)


def test_v11217_content_view_types_and_migration():
    source = _read("app/content_views.py")
    for kind in ("event", "quest", "volunteer_task", "opportunity", "activity", "survey"):
        assert f'"{kind}"' in source
    migration = _read("migrations/versions/20260915_0002_content_views.py")
    assert 'revision: str = "20260915_0002"' in migration
    assert 'down_revision: Union[str, None] = "20260915_0001"' in migration
    assert '"content_views"' in migration


def test_v11217_event_click_isolated_and_telegram_safe():
    source = _read("app/handlers/events.py")
    assert 'F.data.regexp(r"^event:\\d+$")' in source
    assert "Lifecycle refresh failed while opening event" in source
    assert "await session.rollback()" in source
    assert "safe_title = escape(" in source
    assert "safe_description = escape(" in source
    assert "if photo and len(text) <= 950:" in source
    assert 'record_content_view(session, "event"' in source


def test_v11217_views_are_wired_to_all_participant_content():
    expectations = {
        "app/handlers/events.py": 'record_content_view(session, "event"',
        "app/handlers/quests.py": 'record_content_view(session, "quest"',
        "app/handlers/participant_tasks.py": 'record_content_view(session, "volunteer_task"',
        "app/handlers/participant_opportunities.py": 'record_content_view(session, "opportunity"',
        "app/handlers/participant_activities.py": 'record_content_view(session, "activity"',
        "app/handlers/surveys.py": 'record_content_view(session, "survey"',
    }
    for path, needle in expectations.items():
        assert needle in _read(path), path


def test_v11217_admin_templates_show_view_metrics():
    for path in (
        "app/web/templates/events.html",
        "app/web/templates/quests.html",
        "app/web/templates/tasks.html",
        "app/web/templates/opportunities.html",
        "app/web/templates/activities.html",
        "app/web/templates/surveys.html",
    ):
        assert "view_stats" in _read(path), path
    for path in (
        "app/web/templates/event_detail.html",
        "app/web/templates/quest_detail.html",
        "app/web/templates/task_detail.html",
        "app/web/templates/survey_detail.html",
    ):
        source = _read(path)
        assert "view_stat" in source, path
        assert "Перегляд" in source, path


def test_v11217_event_cockpit_alignment_css():
    css = _read("app/web/static/admin.css")
    assert "v1.12.1.7 — Event Operations Cockpit spacing + alignment" in css
    assert ".event-operations-cockpit .event-ops-grid" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert ".event-operations-cockpit .event-ops-inline-actions" in css
    assert "@media(max-width:680px)" in css
    assert ".survey-kpis{max-width:1200px" in css
    assert "repeat(5,minmax(0,1fr))" in css
