from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(rel): return (ROOT/rel).read_text(encoding='utf-8')

def test_version_and_additive_migration():
    assert read('VERSION.txt').strip() == '1.14.0'
    mig=read('migrations/versions/20260917_0003_ambassador_cabinets.py')
    assert 'revision: str = "20260917_0003"' in mig
    assert 'ambassador_responsibility' in mig
    assert 'ambassador_reports' in mig

def test_donation_xp_rate_retroactive_and_idempotent_marker():
    src=read('app/donations.py')
    assert 'DONATION_XP_KOP_PER_POINT = 500' in src
    assert 'backfill_donation_xp' in src
    assert 'auto_link_existing_donations' in src
    assert 'category="donation"' in src
    assert 'donation:{row.provider_transaction_id}' in src
    assert 'affected_users.update(xp_awarded.keys())' in src

def test_support_explains_xp_rate_and_amp_code():
    src=read('app/handlers/donations.py')
    assert '1 XP = 5 грн' in src
    assert 'АМП-{user.id:04d}' in src
    assert 'автоматично донарахує' in src

def test_ambassador_cabinet_reporting_and_responsibility():
    handler=read('app/handlers/ambassadors.py')
    assert 'Кабінет АМПасадора' in handler
    assert 'Подати звіт' in handler
    assert 'AmbassadorReportState' in handler
    assert 'save_telegram_photo' in handler
    route=read('app/web/routes/ambassadors.py')
    assert 'UserRole.ADMIN.value' in route and 'UserRole.SUPERADMIN.value' in route
    assert 'AMBASSADOR_RESPONSIBILITIES' in route

def test_registered_ambassador_can_generate_event_qr():
    events=read('app/handlers/events.py')
    kb=read('app/keyboards.py')
    assert 'ambassador:event_qr:' in events
    assert 'UserRole.AMBASSADOR.value' in events
    assert 'QR-код події' in kb

def test_public_and_own_profile_show_responsibility():
    assert 'Відповідальність' in read('app/handlers/participant_home.py')
    entry=read('app/handlers/start_flow/entry.py')
    assert 'ambassador_responsibility' in entry
    assert 'Статус:' in entry
