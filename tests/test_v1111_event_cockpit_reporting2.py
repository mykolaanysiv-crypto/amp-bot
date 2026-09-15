from pathlib import Path

from app.reports import resolve_report_period

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v1111_version_and_cache_bust():
    version = text("VERSION.txt").strip()
    assert version
    assert text("VERSION_CHECK.txt").strip() == version
    assert f"/static/admin.css?v={text('VERSION.txt').strip()}" in text("app/web/templates/base.html")


def test_event_operations_cockpit_is_single_page_workflow():
    tpl = text("app/web/templates/event_detail.html")
    routes = text("app/web/routes/events.py")
    for phrase in [
        "ОПЕРАЦІЙНИЙ ЦЕНТР",
        "Стан сканера",
        "Масові дії",
        "Оновити чергу та резерви",
        "Підтвердити всіх відмічених",
        "Позначити «Не прийшов»",
    ]:
        assert phrase in tpl
    for phrase in ["Зареєстровані", "Черга / резерв", "Відмітка", "Підтверджено", "XP нараховано", "Відгук"]:
        assert phrase in routes
    assert 'id="event-scanner"' in tpl
    assert "xp_by_user.get(u.id)" in tpl
    assert "feedback_by_user.get(u.id)" in tpl


def test_event_operations_routes_are_scoped_and_audited():
    routes = text("app/web/routes/events.py")
    services = text("app/domain_services/events.py")
    assert '/admin/events/{event_id}/operations/refresh-queue' in routes
    assert '/admin/events/{event_id}/operations/mark-no-show' in routes
    assert "process_event_operations(session, event_id=event.id)" in routes
    assert '"web_event_operations_refresh_queue"' in routes
    assert '"web_event_operations_bulk_no_show"' in routes
    assert "event_id: int | None = None" in services
    assert "EventRegistration.event_id == int(event_id)" in services
    assert "Event.id == int(event_id)" in services


def test_reporting_2_supports_iso_week_and_dynamic_granularity():
    start, end, label = resolve_report_period("week", year=2026, month=38)
    assert (end - start).days == 7
    assert start.isocalendar().week == 38
    assert "38 тиждень 2026" == label
    source = text("app/reports.py")
    assert 'trend_granularity = "day"' in source
    assert 'trend_granularity = "week"' in source
    assert 'trend_granularity = "month"' in source
    assert 'if len(rows)>1:' in source
    assert "Є лише одна точка даних" in source


def test_reporting_2_has_flow_snapshot_funnels_quality_and_definitions():
    source = text("app/reports.py")
    for phrase in [
        "ПОТОКОВІ ПОКАЗНИКИ ЗА ПЕРІОД",
        "МОМЕНТНІ ПОКАЗНИКИ СТАНОМ НА ДАТУ",
        "registration_funnel",
        "event_conversion",
        "data_quality",
        "indicator_definitions",
        "Europe/Kyiv",
        'create_sheet("Воронки")',
        'create_sheet("Якість даних")',
        'create_sheet("Визначення")',
        "Конверсійні воронки",
    ]:
        assert phrase in source


def test_access_log_actor_column_does_not_break_words():
    tpl = text("app/web/templates/audit.html")
    css = text("app/web/static/admin.css")
    assert 'class="audit-log-table"' in tpl
    assert ".audit-log-table th:nth-child(2)" in css
    assert "word-break:keep-all!important" in css
    assert "min-width:150px" in css
