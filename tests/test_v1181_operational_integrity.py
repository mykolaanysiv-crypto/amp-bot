"""v1.18.1: behavior regressions, run by Production Gate with real dependencies."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import event as sqla_event, select

from app.governance import SCAN_SETTING_KEY, reminder_is_overdue, scan_operational_issues
from app.gamification_insights import league_rule_snapshots, leagues_at
from app.model_domains import (
    AuditLog, Event, EventRegistration, GamificationRuleVersion,
    OperationalIssue, SystemSetting, User, XPTransaction,
)
from app.time_utils import clock
from tests.conftest import create_user


@pytest.mark.parametrize('lead', [0, 30, 60, 180])
def test_reminder_grace_no_false_early_alert(lead):
    local_now = clock.local_wall()
    start = local_now + timedelta(minutes=max(lead + 20, 30))
    assert not reminder_is_overdue(start, local_now, lead)
    # A missed run is detected after the 10-minute grace period, not before.
    if lead >= 30:
        due_start = local_now + timedelta(minutes=lead - 11)
        assert reminder_is_overdue(due_start, local_now, lead)


@pytest.mark.asyncio
async def test_issue_auto_reopen_resolve_and_reminder_window(db, monkeypatch):
    async def ok_backup(*args, **kwargs):
        return {'ok': True}

    monkeypatch.setattr('app.governance.backup_verification_status', ok_backup)
    now = clock.storage_utc()
    local_now = clock.local_wall(clock.from_storage_utc(now))
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=1181001)
        user.wallet_xp = -3
        event = Event(title='Scheduled reminder', starts_at=local_now + timedelta(hours=12),
                      checkin_token='v1181-reminder')
        session.add(event)
        await session.flush()
        reg = EventRegistration(event_id=event.id, user_id=user.id, status='registered')
        session.add(reg)
        await session.flush()
        assert await scan_operational_issues(session, now=now) == 1
        wallet = await session.scalar(select(OperationalIssue).where(
            OperationalIssue.fingerprint == f'xp_wallet:{user.id}'))
        assert wallet and wallet.status == 'open'
        assert not await session.scalar(select(OperationalIssue).where(
            OperationalIssue.fingerprint == f'event_no_reminder:{event.id}'))
        wallet.status, wallet.resolution_note = 'resolved', 'Manually resolved'
        await session.flush()
        await scan_operational_issues(session, now=now)
        assert wallet.status == 'open'
        event.starts_at = local_now + timedelta(minutes=35)
        await scan_operational_issues(session, now=now)
        reminder = await session.scalar(select(OperationalIssue).where(
            OperationalIssue.fingerprint == f'event_no_reminder:{event.id}'))
        assert reminder and reminder.status == 'open'
        user.wallet_xp, reg.reminder_1h_sent_at = 0, now
        await scan_operational_issues(session, now=now)
        assert wallet.status == reminder.status == 'resolved'
        assert (await session.get(SystemSetting, SCAN_SETTING_KEY)).value
        actions = set((await session.scalars(select(AuditLog.action))).all())
        assert {'operational_issue_auto_reopened', 'operational_issue_auto_resolved'} <= actions
        await session.rollback()  # Fixtures leave no test-specific persistent data.


@pytest.mark.asyncio
async def test_scanner_uses_one_grouped_ledger_query(db, monkeypatch):
    async def ok_backup(*args, **kwargs):
        return {'ok': True}

    monkeypatch.setattr('app.governance.backup_verification_status', ok_backup)
    async with db.session_factory() as session:
        for n in range(3):
            user = await create_user(session, tg_id=1181100 + n)
            user.wallet_xp = 2 + n
        await session.flush()
        # Count SQL actually sent, not how often the ORM was accessed.
        ledger_queries = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().lower().startswith('select') and 'xp_transactions' in statement.lower():
                ledger_queries.append(statement)

        sqla_event.listen(db.engine.sync_engine, 'before_cursor_execute', capture)
        try:
            await scan_operational_issues(session)
        finally:
            sqla_event.remove(db.engine.sync_engine, 'before_cursor_execute', capture)
        assert len(ledger_queries) == 1
        await session.rollback()


@pytest.mark.asyncio
async def test_league_history_uses_effective_version(db):
    now = clock.storage_utc()
    async with db.session_factory() as session:
        session.add(SystemSetting(key='runtime.league.silver_min', value='200', updated_at=now))
        session.add(GamificationRuleVersion(
            rule_key='league.silver_min', entity_type='league', field_name='threshold',
            old_value='100', new_value='200', author_label='test', reason='Balance review',
            effective_at=now, created_at=now,
        ))
        await session.flush()
        times, snapshots = await league_rule_snapshots(session, now=now + timedelta(seconds=1))
        assert leagues_at(now - timedelta(seconds=1), times, snapshots)[1].min_xp == 100
        assert leagues_at(now + timedelta(seconds=1), times, snapshots)[1].min_xp == 200
        await session.rollback()


def test_stable_package_scripts_and_version():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'VERSION.txt').read_text().strip() == '1.18.1'
    assert (root / 'VERSION_CHECK.txt').read_text().strip() == '1.18.1'
    assert not (root / 'run_all.py').exists()
    for file in ('start_local.sh', 'start_local.ps1'):
        script = (root / file).read_text(encoding='utf-8')
        assert 'scripts.local_supervisor' in script
        assert 'run.py' in script and 'run_web.py' in script
        assert 'run_all.py' not in script
    registry = (root / 'app/jobs/registry.py').read_text(encoding='utf-8')
    assert 'operational_scan_scheduler' in registry
    assert '20260921_0014' in (root / 'migrations/versions/20260921_0014_operational_governance.py').read_text()
