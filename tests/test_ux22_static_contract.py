"""Source-level smoke contracts for UI migration; browser tests remain required."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_shared_dialog_not_cloning_live_forms():
    js=(ROOT/'app/web/static/ux22_modals.js').read_text()
    assert 'body.appendChild(node)' in js
    assert 'cloneNode(' not in js
    assert 'dialog.addEventListener(\'close\',restore)' in js
    assert "form.addEventListener('submit'" in js

def test_all_migrated_create_routes_still_present():
    js=(ROOT/'app/web/static/ux22_modals.js').read_text()
    for page in ('quests','tasks','opportunities','surveys','quick-xp','rewards','badges','activities'):
        assert f"'/admin/{page}'" in js

def test_version_update_uses_superadmin_selector():
    src=(ROOT/'app/web/broadcast_runtime.py').read_text()
    start=src.index('async def _announce_version_update()')
    end=src.index('async def _recover_pending_broadcasts()',start)
    fn=src[start:end]
    assert 'User.role == UserRole.SUPERADMIN.value' in fn
    assert 'User.status == UserStatus.ACTIVE.value' in fn
    assert 'dedupe_key=f"system_version_update:{APP_VERSION}:user:{user.id}"' in fn
