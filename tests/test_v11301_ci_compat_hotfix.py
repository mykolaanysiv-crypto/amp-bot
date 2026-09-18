from __future__ import annotations

from pathlib import Path

from app.models import Base
from tests.source_layout import (
    analytics_source,
    broadcast_runtime_source,
    event_routes_source,
    main_source,
    models_source,
    reports_source,
    start_source,
    web_app_source,
)

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v11301_version_schema_and_alembic_are_stable():
    assert read("VERSION.txt").strip().startswith("1.")
    assert read("VERSION_CHECK.txt").strip().startswith("1.")
    assert len(Base.metadata.tables) == 55
    assert "content_views" in Base.metadata.tables
    migration = read("migrations/versions/20260915_0002_content_views.py")
    assert 'revision: str = "20260915_0002"' in migration


def test_source_layout_helper_resolves_split_canonical_implementations():
    assert 'F.data.startswith("ux:")' in main_source()
    assert "_event_feedback_scheduler" in main_source()
    assert "_smart_opportunities_scheduler" in main_source()

    assert 'callback_data="restore:start"' in start_source()
    assert "RegistrationJourney" in models_source()
    assert "DonationJarState" in models_source()
    assert "Opportunity" in models_source()

    assert '/admin/events/{event_id}/operations/refresh-queue' in event_routes_source()
    assert '@router.get("/tg/event-scanner/{event_id}"' in event_routes_source()
    assert "feedback_stats" in event_routes_source()

    assert '"cohort_funnel"' in analytics_source()
    assert "heatmap_matrix" in analytics_source()
    assert "ПОТОКОВІ ПОКАЗНИКИ ЗА ПЕРІОД" in reports_source()
    assert 'trend_granularity = "day"' in reports_source()

    assert '/admin/security/accounts/{account_id}/permissions' in web_app_source()
    assert 'job_lock(db, f"version_announce:{APP_VERSION}"' in broadcast_runtime_source()


def test_historical_regressions_use_layout_helper_for_split_modules():
    expected = {
        "tests/test_v1100_major_ux.py",
        "tests/test_v1102_permissions_ux.py",
        "tests/test_v1103_data_integrity.py",
        "tests/test_v1104_donations_registrations_ui.py",
        "tests/test_v1110_ux_conversion.py",
        "tests/test_v1111_event_cockpit_reporting2.py",
        "tests/test_v181_features.py",
        "tests/test_v1824_telegram_scanner.py",
        "tests/test_v1825_admin_menu_version_dedupe.py",
        "tests/test_v190_notification_center.py",
        "tests/test_v191_advanced_analytics.py",
        "tests/test_v192_smart_opportunities_seasons.py",
    }
    for rel in expected:
        assert "tests.source_layout" in read(rel), rel


def test_notification_direct_send_allowlist_tracks_new_auth_route():
    test_source = read("tests/test_v190_notification_center.py")
    assert '"app/web/auth_routes.py"' in test_source
    assert '"app/web/app.py"' not in test_source[test_source.index("def test_all_proactive_telegram_delivery_uses_canonical_center"):test_source.index("def test_runtime_health_direct_delivery")]

    offenders: list[str] = []
    allowed = {"app/reliability.py", "app/web/auth_routes.py", "app/runtime_health.py"}
    for path in (ROOT / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "bot.send_message" not in source:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel not in allowed:
            offenders.append(rel)
    assert offenders == []


def test_scanner_regression_targets_canonical_event_operations_module():
    startup_test = read("tests/test_v1822_startup_hotfix.py")
    assert 'ROOT / "app" / "web" / "event_routes" / "operations.py"' in startup_test
    assert 'ROOT / "app" / "web" / "event_routes"' in startup_test
