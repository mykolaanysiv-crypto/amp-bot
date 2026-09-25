"""Dependency-free packaging gates; functional tests live in v1181_operational_integrity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def test_version_and_inherited_alembic_head():
    assert read('VERSION.txt').strip() == read('VERSION_CHECK.txt').strip() == '1.18.1'
    assert 'revision = "20260921_0014"' in read('migrations/versions/20260921_0014_operational_governance.py')
    assert not list((ROOT / 'migrations/versions').glob('*0015*'))


def test_dashboard_and_get_operations_do_not_scan_database():
    assert 'scan_operational_issues' not in read('app/web/routes/dashboard.py')
    page = read('app/web/routes/operations.py')
    assert "@router.post('/admin/operations/scan')" in page
    assert "@router.get('/admin/operations'" in page
    assert "async with job_lock(db, 'operational_scan'" in page


def test_background_scan_is_supervised_and_healthy():
    job = read('app/jobs/operations.py')
    registry = read('app/jobs/registry.py')
    health = read('app/runtime_health.py')
    assert 'scan_operational_issues(session)' in job
    assert 'job_lock(db, "operational_scan"' in job
    assert 'await session.commit()' in job
    assert 'asyncio.sleep(15 * 60)' in job
    assert 'operational_scan_scheduler' in registry and 'operational_scan_scheduler' in health


def test_no_per_user_xp_select_and_scanner_has_completion_marker():
    governance = read('app/governance.py')
    assert 'group_by(User.id, User.wallet_xp)' in governance
    assert 'select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(XPTransaction.user_id' not in governance
    assert 'SCAN_SETTING_KEY' in governance
    assert 'operational_issue_auto_reopened' in governance
    assert 'operational_issue_auto_resolved' in governance
    assert 'reminder_is_overdue' in governance


def test_leagues_history_and_input_bounds():
    route = read('app/web/routes/governance.py')
    analytics = read('app/gamification_insights.py')
    assert 'ordered[0] < 1' in route
    assert 'league_rule_snapshots' in analytics
    assert 'GamificationRuleVersion.effective_at <= now' in analytics
    assert 'before < league.min_xp <= cumulative' in analytics


def test_local_entrypoints_and_frontend_cache_versions():
    assert not (ROOT / 'run_all.py').exists()
    for script in ('start_local.sh', 'start_local.ps1'):
        source = read(script)
        assert 'scripts.local_supervisor' in source
        assert 'run_web.py' in source and 'run.py' in source
        assert 'run_all.py' not in source
    for path in ('base.html', 'login.html', 'login_2fa.html'):
        assert 'v=1.18.1' in read(f'app/web/templates/{path}')


def test_shared_local_supervisor_runs_both_canonical_processes():
    source = read('scripts/local_supervisor.py')
    assert 'subprocess.Popen' in source
    assert 'run_web.py' in source and 'run.py' in source
    assert 'child.terminate()' in source and 'child.wait(' in source
