from pathlib import Path


def test_version_11215_or_newer():
    version = Path("VERSION.txt").read_text().strip()
    check = Path("VERSION_CHECK.txt").read_text().strip()
    assert version == check
    assert tuple(int(part) for part in version.split(".")) >= (1, 12, 1, 5)


def test_backup_unknown_grace_is_configurable_and_used():
    config = Path("app/config.py").read_text()
    reliability = Path("app/reliability.py").read_text()
    main = Path("app/main.py").read_text()
    assert "BACKUP_UNKNOWN_GRACE_HOURS" in config
    assert "monitor.backup.unknown_since" in reliability
    assert 'status": "initializing"' in reliability
    assert "unknown_grace_hours=settings.backup_unknown_grace_hours" in main


def test_verified_backup_resets_initial_unknown_state():
    source = Path("app/reliability.py").read_text()
    assert '"monitor.backup.unknown_since", "monitor.backup.last_alert_at"' in source
    assert "await session.delete(marker)" in source


def test_ci_captures_verified_backup_before_deploy():
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert "Capture and verify PostgreSQL backup before deploy" in workflow
    assert 'heroku pg:backups:capture -a "$HEROKU_APP_NAME"' in workflow
    assert "scripts.mark_backup_verified" in workflow
    assert "scripts.verify_backup_marker" in workflow
    assert workflow.index("Capture and verify PostgreSQL backup before deploy") < workflow.index("Deploy tested commit to Heroku")


def test_daily_backup_workflow_exists():
    workflow = Path(".github/workflows/backup.yml").read_text()
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "heroku pg:backups:capture" in workflow
    assert "scripts.mark_backup_verified" in workflow
    assert "scripts.verify_backup_marker" in workflow


def test_system_health_distinguishes_initializing_backup():
    template = Path("app/web/templates/system_health.html").read_text()
    assert "очікує першої автоматичної перевірки" in template
    assert "копія застаріла" in template
