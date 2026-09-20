from __future__ import annotations

from pathlib import Path

from app.field_crypto import clear_keyring_cache, decrypt_field, encrypt_field, is_encrypted

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1172_version_and_alembic_head():
    assert read("VERSION.txt").strip() == "1.17.2"
    assert read("VERSION_CHECK.txt").strip() == "1.17.2"
    migration = read("migrations/versions/20260920_0010_privacy_data_integrity.py")
    assert 'revision: str = "20260920_0010"' in migration
    assert 'down_revision: Union[str, None] = "20260920_0009"' in migration


def test_sensitive_fields_are_transparently_encrypted(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "v1172-current-field-key-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", "")
    clear_keyring_cache()
    value = '["disability","veteran_family"]'
    encrypted = encrypt_field(value)
    assert encrypted and encrypted != value and is_encrypted(encrypted)
    assert decrypt_field(encrypted) == value
    identity = read("app/model_domains/identity.py")
    for field in ("vulnerability_categories", "restoration_answers_json", "deletion_reason", "registration_rejection_reason"):
        assert f"{field}: Mapped[str | None] = mapped_column(EncryptedText()" in identity
    clear_keyring_cache()


def test_key_rotation_supports_previous_key(monkeypatch):
    old = "v1172-old-field-key-abcdefghijklmnopqrstuvwxyz"
    new = "v1172-new-field-key-abcdefghijklmnopqrstuvwxyz"
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", old)
    monkeypatch.setenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", "")
    clear_keyring_cache()
    payload = encrypt_field("secret-profile-data")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", new)
    monkeypatch.setenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", old)
    clear_keyring_cache()
    assert decrypt_field(payload) == "secret-profile-data"
    clear_keyring_cache()


def test_data_integrity_center_contains_requested_checks():
    source = read("app/data_integrity.py")
    for token in (
        "duplicate_phone", "duplicate_email", "duplicate_profile", "orphan_records",
        "wallet_xp_mismatch", "reward_claim_inconsistency", "attendance_anomaly",
        "invalid_event_status", "expired_reservation", "missing_media",
    ):
        assert token in source
    route = read("app/web/routes/data_integrity.py")
    assert 'guard_superadmin(request)' in route
    assert '/admin/data-integrity/retention-cleanup' in route
    assert '/admin/data-integrity/refresh-event-operations' in route


def test_retention_is_conservative_and_auditable():
    source = read("app/privacy_retention.py")
    for token in ("RegistrationJourney", "WebAdminSession", "Notification", "NotificationDelivery", "MediaAsset"):
        assert token in source
    assert "XPTransaction" not in source
    assert "EventRegistration" not in source
    assert "AuditLog" not in source
    assert '"privacy_retention_cleanup"' in source
    registry = read("app/jobs/registry.py")
    assert '"privacy_retention_scheduler"' in registry


def test_sensitive_profile_and_document_downloads_are_audited():
    users = read("app/web/routes/users.py")
    media = read("app/web/media_routes.py")
    assert "web_user_profile_view_sensitive" in users
    assert "web_sensitive_document_download" in users
    assert "web_sensitive_media_download" in media


def test_backup_workflow_restores_real_backup_to_ephemeral_postgres():
    workflow = read(".github/workflows/backup.yml")
    script = read("scripts/verify_backup_restore.sh")
    assert "postgres:16" in workflow
    assert "verify_backup_restore.sh" in workflow
    assert "restore-verified" in workflow
    assert "pg_restore" in script
    assert "AMP_ALLOW_TEMP_RESTORE" in script
    assert "alembic_version" in script
