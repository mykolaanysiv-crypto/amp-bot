from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1171_version_and_alembic_head():
    version = read("VERSION.txt").strip()
    assert tuple(map(int, version.split("."))) >= (1, 17, 1)
    assert read("VERSION_CHECK.txt").strip() == version
    migration = read("migrations/versions/20260920_0009_alembic_full_adoption.py")
    assert 'revision: str = "20260920_0009"' in migration
    assert 'down_revision: Union[str, None] = "20260920_0008"' in migration


def test_runtime_db_init_never_mutates_schema():
    db = read("app/db.py")
    assert "_migrate_v10_to_v11" not in db
    assert "Base.metadata.create_all" not in db
    assert "CREATE TABLE" not in db.upper()
    assert "ALTER TABLE" not in db.upper()
    assert 'exec_driver_sql("SELECT 1")' in db


def test_release_migrates_before_runtime_initialization():
    smoke = read("scripts/startup_smoke.py")
    migrate = smoke.index("upgrade_head()")
    db_init = smoke.index("asyncio.run(_db_init_phase())", migrate)
    bootstrap = smoke.index("asyncio.run(_bootstrap_defaults_phase())", db_init)
    web = smoke.index("asyncio.run(_web_startup_phase())", bootstrap)
    assert migrate < db_init < bootstrap < web


def test_frozen_baseline_is_alembic_owned_not_runtime_metadata_create_all():
    baseline = read("migrations/versions/20260915_0001_v1111_baseline.py")
    assert "op.create_table(" in baseline
    assert "Base.metadata.create_all" not in baseline
    assert "def upgrade()" in baseline
    assert "def downgrade()" in baseline


def test_retired_compatibility_facades_are_gone():
    for rel in (
        "app/models.py", "app/services.py", "app/analytics.py", "app/reports.py",
        "app/web/app.py", "app/web/routes/events.py", "app/handlers/start.py",
    ):
        assert not (ROOT / rel).exists(), rel


def test_ci_rejects_schema_drift_and_runs_migration_roundtrip():
    ci = read(".github/workflows/ci.yml")
    assert "python -m scripts.schema_drift_check" in ci
    assert "test_alembic_upgrade_from_previous_production_schema" in ci
    assert "test_latest_revision_downgrade_upgrade_roundtrip" in ci
    assert (ROOT / "scripts/schema_drift_check.py").exists()
