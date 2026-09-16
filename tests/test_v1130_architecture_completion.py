from __future__ import annotations

import ast
from pathlib import Path

from app.models import Base

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1130_version_manifest_and_schema_continuity():
    assert read("VERSION.txt").strip() == "1.13.0"
    assert read("VERSION_CHECK.txt").strip() == "1.13.0"
    assert len(Base.metadata.tables) == 54
    assert "content_views" in Base.metadata.tables
    versions = sorted(path.name for path in (ROOT / "migrations" / "versions").glob("*.py"))
    assert any("20260915_0002_content_views" in name for name in versions)
    assert not any("1130" in name.lower() for name in versions)


def test_web_uses_application_factory_and_keeps_small_compatibility_facade():
    factory = read("app/web/factory.py")
    facade = read("app/web/app.py")
    runner = read("run_web.py")
    assert "def create_app() -> FastAPI:" in factory
    assert "from .factory import create_app" in facade
    assert "app = create_app()" in facade
    assert len(facade.splitlines()) < 80
    assert '"app.web.factory:create_app"' in runner
    assert "factory=True" in runner


def test_web_dependencies_health_lifespan_and_broadcast_runtime_are_split():
    for rel in (
        "app/web/dependencies.py",
        "app/web/health_routes.py",
        "app/web/auth_routes.py",
        "app/web/media_routes.py",
        "app/web/lifespan.py",
        "app/web/broadcast_runtime.py",
    ):
        assert (ROOT / rel).exists(), rel
    health = read("app/web/health_routes.py")
    assert 'router.get("/health/live")' in health
    assert 'router.get("/health/ready")' in health
    assert 'router.get("/health/dependencies")' in health
    assert "JSONResponse(jsonable_encoder(payload)" in health


def test_event_routes_are_domain_split_behind_compatibility_facade():
    facade = read("app/web/routes/events.py")
    assert "from app.web.event_routes import router" in facade
    assert len(facade.splitlines()) < 80
    expected = {
        "context.py",
        "scanner_common.py",
        "telegram_scanner.py",
        "public.py",
        "overview.py",
        "participants.py",
        "operations.py",
        "mutations.py",
    }
    actual = {path.name for path in (ROOT / "app" / "web" / "event_routes").glob("*.py")}
    assert expected <= actual


def test_analytics_and_reports_are_split_behind_explicit_facades():
    analytics = read("app/analytics.py")
    reports = read("app/reports.py")
    assert "from .analytics_modules import" in analytics
    assert "from .reporting import" in reports
    assert "import *" not in analytics
    assert "import *" not in reports
    assert len(analytics.splitlines()) < 80
    assert len(reports.splitlines()) < 80
    assert (ROOT / "app" / "analytics_modules" / "core.py").exists()
    assert (ROOT / "app" / "analytics_modules" / "exports.py").exists()
    assert (ROOT / "app" / "reporting" / "periods.py").exists()
    assert (ROOT / "app" / "reporting" / "builder.py").exists()
    assert (ROOT / "app" / "reporting" / "exports.py").exists()


def test_models_are_split_by_domain_with_explicit_compatibility_exports():
    facade = read("app/models.py")
    assert "from .model_domains import (" in facade
    assert "import *" not in facade
    assert len(facade.splitlines()) < 180
    expected = {
        "base.py",
        "identity.py",
        "gamification.py",
        "events.py",
        "engagement.py",
        "donations.py",
        "communications.py",
    }
    actual = {path.name for path in (ROOT / "app" / "model_domains").glob("*.py")}
    assert expected <= actual


def test_start_and_main_are_small_orchestration_facades_and_jobs_are_split():
    start = read("app/handlers/start.py")
    main = read("app/main.py")
    registry = read("app/jobs/registry.py")
    assert "from .start_flow import router, help_command" in start
    assert len(start.splitlines()) < 80
    assert len(main.splitlines()) < 140
    assert "scheduler_factories" in main
    scheduler_names = (
        "birthday_scheduler",
        "event_reminder_scheduler",
        "event_feedback_scheduler",
        "goal_reward_scheduler",
        "streak_scheduler",
        "notification_retry_scheduler",
        "participant_inactivity_scheduler",
        "smart_opportunities_scheduler",
        "season_history_scheduler",
        "donation_sync_scheduler",
        "notification_health_scheduler",
        "backup_health_scheduler",
        "content_lifecycle_scheduler",
    )
    for name in scheduler_names:
        assert f'"{name}"' in registry
    assert len(scheduler_names) == 13
    assert (ROOT / "app" / "bot_runtime.py").exists()
    assert (ROOT / "app" / "telegram_middleware.py").exists()


def test_application_code_has_no_wildcard_imports():
    hits: list[str] = []
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                hits.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert hits == []


def test_compatibility_facades_declare_transition_window():
    for rel in (
        "app/models.py",
        "app/analytics.py",
        "app/reports.py",
        "app/web/app.py",
        "app/web/routes/events.py",
        "app/handlers/start.py",
    ):
        text = read(rel).lower()
        assert "compatibility" in text
        assert "1–2" in text or "1-2" in text


def test_startup_smoke_exercises_factory_and_compatibility_import():
    smoke = read("scripts/startup_smoke.py")
    assert 'importlib.import_module("app.web.factory")' in smoke
    assert "factory_module.create_app()" in smoke
    assert 'importlib.import_module("app.web.app")' in smoke
    assert 'importlib.import_module("app.main")' in smoke


def test_production_preflight_guards_architecture_completion():
    src = read("scripts/production_preflight.py")
    assert "Architecture preflight failed" in src
    assert "wildcard imports remain" in src
    assert "app.web.factory.create_app missing" in src
    assert "facade_limits" in src
    assert '20260915_0002_content_views.py' in src
