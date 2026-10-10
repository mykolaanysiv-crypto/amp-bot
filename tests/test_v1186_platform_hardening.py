from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import get_settings
from app.field_crypto import clear_keyring_cache, decrypt_field, encrypt_field
from app.web.security_middleware import CSRFMiddleware


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1186_version_runtime_and_cache_tokens_are_synchronized():
    assert read("VERSION.txt").strip() == "1.20.3"
    assert read("VERSION_CHECK.txt").strip() == "1.20.3"
    assert '"1.20.3"' in read("app/version.py")
    assert "FROM python:3.13-slim" in read("Dockerfile")
    assert read(".python-version").strip() == "3.13"
    for template in ("base.html", "login.html", "login_2fa.html"):
        assert "v=1.20.3" in read(f"app/web/templates/{template}")


def test_v1186_ci_has_js_static_backup_and_postdeploy_gates():
    ci = read(".github/workflows/ci.yml")
    for token in (
        "image: public.ecr.aws/docker/library/postgres:18",
        "node tests/js/test_admin_forms.js",
        "ruff check --select E9,F63,F7,F82",
        "pip-audit -r requirements.lock",
        "Restore-verify fresh pre-deploy backup",
        "scripts.mark_backup_verified",
        "Post-deploy readiness and version smoke",
        "scripts.rotate_field_encryption",
    ):
        assert token in ci
    assert read(".github/dependabot.yml").startswith("version: 2")


def test_production_requires_distinct_dedicated_field_encryption_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DYNO", "web.1")
    monkeypatch.setenv("AMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/amp_bot.db")
    monkeypatch.setenv("WEB_SESSION_SECRET", "session-secret-abcdefghijklmnopqrstuvwxyz-123456")
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY"):
        get_settings(require_bot_token=False)

    session_secret = "session-secret-abcdefghijklmnopqrstuvwxyz-123456"
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", session_secret)
    with pytest.raises(RuntimeError, match="відрізнятися"):
        get_settings(require_bot_token=False)

    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "field-secret-ABCDEFGHIJKLMNOPQRSTUVWXYZ-987654")
    settings = get_settings(require_bot_token=False)
    assert settings.backup_warning_age_hours == 36
    assert settings.backup_max_age_hours == 48
    assert settings.web_max_request_bytes == 25 * 1024 * 1024


def test_field_crypto_reads_legacy_session_secret_after_dedicated_key_is_introduced(monkeypatch):
    old_session_secret = "legacy-session-secret-abcdefghijklmnopqrstuvwxyz"
    new_field_key = "new-field-secret-ABCDEFGHIJKLMNOPQRSTUVWXYZ-123456"

    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("WEB_SESSION_SECRET", old_session_secret)
    monkeypatch.setenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", "")
    clear_keyring_cache()
    payload = encrypt_field("sensitive-legacy-value")

    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", new_field_key)
    monkeypatch.setenv("WEB_SESSION_SECRET", old_session_secret)
    monkeypatch.setenv("FIELD_ENCRYPTION_PREVIOUS_KEYS", "")
    clear_keyring_cache()
    assert decrypt_field(payload) == "sensitive-legacy-value"
    clear_keyring_cache()


def test_admin_request_limit_rejects_oversized_content_length_before_downstream():
    called = False
    sent: list[dict] = []

    async def app(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    middleware = CSRFMiddleware(app, max_body_bytes=1024)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/admin/events/create",
        "headers": [(b"content-length", b"1025")],
    }
    asyncio.run(middleware(scope, receive, send))

    assert not called
    response_start = next(message for message in sent if message["type"] == "http.response.start")
    assert response_start["status"] == 413


def test_backup_and_media_integrity_hardening_source_gates():
    reliability = read("app/reliability.py")
    assert "max_age_hours: int = 48" in reliability
    assert "warning_age_hours: int = 36" in reliability
    assert 'status_name = "warning"' in reliability

    integrity = read("app/data_integrity.py")
    assert "_referenced_database_media_ids" in integrity
    assert '"orphan_media_assets"' in integrity
    assert "Автоматичне видалення не виконується" in integrity

    system_template = read("app/web/templates/system_health.html")
    assert "скоро потрібна свіжа копія" in system_template
