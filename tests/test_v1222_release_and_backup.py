from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]

def test_release_version_matches_and_preflight_not_hardcoded():
    from app.version import APP_VERSION
    current = (ROOT / 'VERSION.txt').read_text().strip()
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", current)
    assert (ROOT / 'VERSION_CHECK.txt').read_text().strip() == APP_VERSION == current

def test_ci_invokes_backup_verifier_portably_and_limits_deploy():
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    backup = (ROOT / '.github/workflows/backup.yml').read_text()
    for workflow in (ci, backup):
        assert 'bash ./scripts/verify_backup_restore.sh "$HEROKU_APP_NAME"' in workflow
    assert "github.ref == 'refs/heads/main'" in ci
    script = (ROOT / 'scripts/verify_backup_restore.sh').read_text()
    assert 'AMP_ALLOW_TEMP_RESTORE' in script
    assert 'RESTORE_DATABASE_URL' in script
    assert 'pg_restore' in script
