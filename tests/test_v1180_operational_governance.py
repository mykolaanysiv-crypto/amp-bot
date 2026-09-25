from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def text(p): return (ROOT/p).read_text(encoding='utf-8')

def test_version_and_migration():
    assert text('VERSION.txt').strip()=='1.18.1'
    assert text('VERSION_CHECK.txt').strip()=='1.18.1'
    m=text('migrations/versions/20260921_0014_operational_governance.py')
    assert 'revision = "20260921_0014"' in m and 'down_revision = "20260921_0013"' in m
    assert 'operational_issues' in m and 'gamification_rule_versions' in m

def test_operational_center_is_actionable():
    r=text('app/web/routes/operations.py'); t=text('app/web/templates/operations.html'); g=text('app/governance.py')
    for token in ['registration_stale','failed_notifications','event_no_reminder','feedback_low','expired_reservations','xp_anomaly','backup_stale']:
        assert token in g
    assert '/assign' in r and '/resolve' in r and '/reopen' in r
    assert 'Перейти до проблеми' in t and 'Відповідальний' in t and 'severity-' in t

def test_gamification_change_control_is_append_only():
    g=text('app/governance.py'); t=text('app/web/templates/gamification_governance.html')
    assert 'GamificationRuleVersion' in g and 'old_value' in g and 'new_value' in g
    assert 'effective_at' in g and 'reason' in g and 'author_label' in g
    assert 'Історичний баланс XP автоматично не перераховується' in t

def test_governed_sources_record_xp_rule_changes():
    for path in ['app/web/event_routes/mutations.py','app/web/routes/quests.py','app/web/routes/tasks.py','app/web/routes/activities.py','app/web/routes/surveys.py','app/web/routes/quick_xp.py','app/web/routes/gamification.py','app/web/routes/ambassadors.py']:
        assert 'record_field_changes' in text(path), path

def test_league_thresholds_are_runtime_driven():
    leagues=text('app/leagues.py'); gov=text('app/web/routes/governance.py')
    assert 'async def runtime_leagues' in leagues
    for key in ['league.silver_min','league.gold_min','league.platinum_min','league.diamond_min','league.legendary_min']:
        assert key in leagues and key in gov
