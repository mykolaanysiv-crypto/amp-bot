from pathlib import Path


def test_procfile_splits_web_and_worker():
    text = Path("Procfile").read_text()
    assert "web: python run_web.py" in text
    assert "worker: python run.py" in text
    assert "web: python run_all.py" not in text


def test_services_is_compatibility_facade():
    text = Path("app/services.py").read_text()
    assert "Compatibility" in text or "compatib" in text.lower()
    assert "import *" not in text
    expected = {"users.py", "events.py", "gamification.py", "referrals.py", "exports.py", "bootstrap.py"}
    assert expected.issubset({p.name for p in Path("app/domain_services").glob("*.py")})


def test_large_telegram_handlers_are_split():
    assert len(Path("app/handlers/admin.py").read_text().splitlines()) < 30
    assert len(Path("app/handlers/participant.py").read_text().splitlines()) < 30
    assert len(list(Path("app/handlers").glob("admin_*.py"))) >= 6
    assert len(list(Path("app/handlers").glob("participant_*.py"))) >= 5


def test_alembic_baseline_present():
    assert Path("alembic.ini").exists()
    versions = list(Path("migrations/versions").glob("*.py"))
    assert versions
    assert "20260915_0001" in versions[0].read_text()


def test_ci_has_postgres_service():
    text = Path(".github/workflows/ci.yml").read_text()
    assert "postgres:16" in text
    assert "tests/integration" in text
    assert "push:" in text


def test_production_observability_and_backup_checks_present():
    obs = Path("app/observability.py").read_text()
    reliability = Path("app/reliability.py").read_text()
    main = Path("app/main.py").read_text()
    jobs = Path("app/jobs/delivery.py").read_text()
    assert "JsonLogFormatter" in obs
    assert "SensitiveDataFilter" in obs
    assert "SENTRY_DSN" in obs
    assert "notification_failure_alert" in reliability
    assert "backup_health_alert" in reliability
    assert "_notification_health_scheduler" in jobs
    assert "_backup_health_scheduler" in jobs
    assert "scheduler_factories" in main


def test_gamification_20_is_analysis_only_and_uses_clean_baseline():
    text = Path("app/gamification_insights.py").read_text()
    assert "gamification.clean_data_start" in text
    assert "XPTransaction.created_at >= baseline" in text
    assert "observation_days < 28" in text
    assert "observation_days < 56" in text
    assert "add_xp(" not in text
    assert "Система не змінює XP автоматично" in text


def test_release_phase_runs_migrations_and_preflight():
    release = Path("scripts/heroku_release.py").read_text()
    smoke = Path("scripts/startup_smoke.py").read_text()
    assert "startup_smoke()" in release
    assert "upgrade_head" in smoke
    assert "production_preflight" in release
    assert Path("scripts/heroku_capture_verified_backup.sh").exists()
