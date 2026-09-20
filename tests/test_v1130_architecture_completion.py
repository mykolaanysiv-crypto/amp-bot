from __future__ import annotations

import ast
from pathlib import Path

from app.model_domains import Base

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1130_version_manifest_and_schema_continuity():
    version = read("VERSION.txt").strip()
    assert version.startswith("1.")
    assert read("VERSION_CHECK.txt").strip() == version
    assert len(Base.metadata.tables) >= 55
    assert "content_views" in Base.metadata.tables
    versions = sorted(path.name for path in (ROOT / "migrations" / "versions").glob("*.py"))
    assert any("20260915_0002_content_views" in name for name in versions)
    assert any("20260920_0009_alembic_full_adoption" in name for name in versions)


def test_web_uses_application_factory_without_compatibility_facade():
    factory = read("app/web/factory.py")
    runner = read("run_web.py")
    assert "def create_app() -> FastAPI:" in factory
    assert not (ROOT / "app/web/app.py").exists()
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


def test_event_routes_are_domain_split_without_compatibility_facade():
    assert not (ROOT / "app/web/routes/events.py").exists()
    expected = {
        "context.py", "scanner_common.py", "telegram_scanner.py", "public.py",
        "overview.py", "participants.py", "operations.py", "mutations.py",
    }
    actual = {path.name for path in (ROOT / "app/web/event_routes").glob("*.py")}
    assert expected <= actual
    factory = read("app/web/factory.py")
    assert "event_routes" in factory


def test_analytics_reports_and_models_use_canonical_packages_only():
    for retired in ("app/analytics.py", "app/reports.py", "app/models.py", "app/services.py"):
        assert not (ROOT / retired).exists(), retired
    assert (ROOT / "app/analytics_modules/core.py").exists()
    assert (ROOT / "app/analytics_modules/exports.py").exists()
    assert (ROOT / "app/reporting/periods.py").exists()
    assert (ROOT / "app/reporting/builder.py").exists()
    assert (ROOT / "app/reporting/exports.py").exists()
    expected_models = {
        "base.py", "identity.py", "gamification.py", "events.py", "engagement.py",
        "donations.py", "communications.py",
    }
    actual_models = {path.name for path in (ROOT / "app/model_domains").glob("*.py")}
    assert expected_models <= actual_models


def test_start_and_main_use_canonical_modules_and_jobs_are_split():
    assert not (ROOT / "app/handlers/start.py").exists()
    main = read("app/main.py")
    bot_runtime = read("app/bot_runtime.py")
    registry = read("app/jobs/registry.py")
    assert len(main.splitlines()) < 140
    assert "scheduler_factories" in main
    assert "start_flow" in bot_runtime
    scheduler_names = (
        "birthday_scheduler", "event_reminder_scheduler", "event_feedback_scheduler",
        "goal_reward_scheduler", "streak_scheduler", "notification_retry_scheduler",
        "participant_inactivity_scheduler", "smart_opportunities_scheduler",
        "season_history_scheduler", "donation_sync_scheduler",
        "notification_health_scheduler", "backup_health_scheduler",
        "content_lifecycle_scheduler",
    )
    for name in scheduler_names:
        assert f'"{name}"' in registry
    assert len(scheduler_names) == 13
    assert (ROOT / "app/bot_runtime.py").exists()
    assert (ROOT / "app/telegram_middleware.py").exists()


def test_application_code_has_no_wildcard_imports():
    hits: list[str] = []
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                hits.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert hits == []


def test_internal_code_does_not_import_retired_facades():
    banned = {"app.models", "app.services", "app.analytics", "app.reports", "app.web.app", "app.web.routes.events", "app.handlers.start"}
    hits: list[str] = []
    for base in (ROOT / "app", ROOT / "scripts"):
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in banned:
                    hits.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in banned:
                            hits.append(f"{path.relative_to(ROOT)}:{node.lineno}:{alias.name}")
    assert hits == []


def test_startup_smoke_exercises_canonical_factory_only():
    smoke = read("scripts/startup_smoke.py")
    assert 'importlib.import_module("app.web.factory")' in smoke
    assert "factory_module.create_app()" in smoke
    assert 'importlib.import_module("app.web.app")' not in smoke
    assert 'importlib.import_module("app.main")' in smoke
    assert smoke.index("upgrade_head()") < smoke.index("asyncio.run(_db_init_phase())")


def test_production_preflight_guards_architecture_and_alembic_adoption():
    src = read("scripts/production_preflight.py")
    assert "Architecture preflight failed" in src
    assert "wildcard imports remain" in src
    assert "app.web.factory.create_app missing" in src
    assert "retired_facades" in src
    assert "_migrate_v10_to_v11" in src
    assert "schema_drift_check.py" in src
