"""v1.21.0 full-release gates for files that must never be patch-only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")



CURRENT_VERSION = (Path(__file__).resolve().parents[1] / "VERSION.txt").read_text(encoding="utf-8").strip()

def test_v1185_version_and_cache_tokens_are_synchronized():
    assert read("VERSION.txt").strip() == CURRENT_VERSION
    assert read("VERSION_CHECK.txt").strip() == CURRENT_VERSION
    assert "_read_version()" in read("app/version.py")
    for path in ("base.html", "login.html", "login_2fa.html"):
        assert f"v={CURRENT_VERSION}" in read(f"app/web/templates/{path}")


def test_v1185_full_release_contains_qr_quest_service_and_pg18_backup_verifier():
    quest_auto = ROOT / "app/domain_services/quest_auto.py"
    assert quest_auto.exists() and quest_auto.stat().st_size > 1000
    events = read("app/domain_services/events.py")
    assert "from .quest_auto import" in events
    assert "image: public.ecr.aws/docker/library/postgres:18" in read(".github/workflows/backup.yml")
    restore = read("scripts/verify_backup_restore.sh")
    assert "public.ecr.aws/docker/library/postgres:18" in restore
    assert "pg_restore --no-owner --no-acl" in restore
    assert "AMP_ALLOW_TEMP_RESTORE" in restore
    assert "RESTORE_DATABASE_URL" in restore


def test_v1185_keeps_current_alembic_head():
    assert 'revision = "20260925_0015"' in read("migrations/versions/20260925_0015_quest_qr_on_time.py")
