from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_is_v1121():
    version = read("VERSION.txt").strip()
    assert tuple(map(int, version.split("."))) >= (1, 12, 1)
    assert read("VERSION_CHECK.txt").strip() == version


def test_release_runs_real_lifecycle_smoke_before_preflight():
    src = read("scripts/heroku_release.py")
    assert "from scripts.startup_smoke import run as startup_smoke" in src
    assert "startup_smoke()" in src
    assert src.index("startup_smoke()") < src.index("production_preflight()")


def test_startup_smoke_covers_required_order_and_real_web_lifespan():
    src = read("scripts/startup_smoke.py")
    required = [
        "await db.init()",
        "await bootstrap_defaults(db, settings)",
        "upgrade_head()",
        "app.router.lifespan_context(app)",
        'importlib.import_module("app.main")',
    ]
    for token in required:
        assert token in src
    # Additive Alembic revisions must be applied before bootstrap_defaults can
    # issue ORM SELECTs against models containing the new mapped columns.
    db_init = src.index("asyncio.run(_db_init_phase())")
    migrate = src.index("upgrade_head()", db_init)
    bootstrap = src.index("asyncio.run(_bootstrap_defaults_phase())", migrate)
    web = src.index("asyncio.run(_web_startup_phase())", bootstrap)
    assert db_init < migrate < bootstrap < web


def test_ci_has_postgres16_real_release_gate_and_deploy_dependency():
    src = read(".github/workflows/ci.yml")
    assert "image: postgres:16" in src
    assert "Real release/startup smoke on PostgreSQL 16" in src
    assert "python -m scripts.heroku_release" in src
    assert "needs: test" in src
    assert "github.ref == 'refs/heads/main'" in src


def test_procfile_keeps_separate_release_web_worker():
    src = read("Procfile")
    assert "release: python -m scripts.heroku_release" in src
    assert "web: python run_web.py" in src
    assert "worker: python run.py" in src


def test_health_endpoints_are_split_by_semantics():
    src = read("app/web/health_routes.py")
    for endpoint in ("/health/live", "/health/ready", "/health/dependencies"):
        assert endpoint in src
    assert "database_probe" in src
    assert "alembic_revision_status" in src
    assert "runtime_health_snapshot" in src
    assert '"Cache-Control": "no-store"' in src


def test_postgres_pool_limits_are_explicit_and_configurable():
    cfg = read("app/config.py")
    db = read("app/db.py")
    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
    ):
        assert name in cfg
    for token in ("pool_size=", "max_overflow=", "pool_timeout=", "pool_recycle="):
        assert token in db


def test_worker_and_scheduler_heartbeats_are_supervised():
    runtime = read("app/runtime_health.py")
    main = read("app/main.py")
    registry = read("app/jobs/registry.py")
    assert "async def heartbeat_loop" in runtime
    assert "async def supervise_scheduler" in runtime
    assert "SCHEDULER_MAX_SILENCE_SECONDS" in runtime
    assert "_direct_superadmin_alert" in runtime
    assert "heartbeat_loop(" in main and '"worker"' in main
    assert "supervise_scheduler(" in main
    assert "scheduler_factories" in registry


def test_postgres_integration_test_is_real_db_test():
    src = read("tests/integration/test_postgres_smoke.py")
    assert "TEST_DATABASE_URL" in src
    assert "await db.init()" in src
    assert "Base.metadata.drop_all" in src
    assert "notifications" in src
