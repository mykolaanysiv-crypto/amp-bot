from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.metrics import RuntimeMetrics
from app.permissions import required_web_permission
from app.rate_limit import RateLimitRule, SlidingWindowRateLimiter, classify_rate_limit
from app.web.security_middleware import SecurityHeadersMiddleware

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1190_release_version_schema_and_dependency_contract():
    assert read("VERSION.txt").strip() == "1.20.1"
    assert read("VERSION_CHECK.txt").strip() == "1.20.1"
    assert '"1.20.1"' in read("app/version.py")
    migration = read("migrations/versions/20261007_0016_security_observability.py")
    assert 'revision: str = "20261007_0016"' in migration
    assert 'down_revision: Union[str, None] = "20260925_0015"' in migration
    assert 'op.create_table(\n        "web_authn_credentials"' in migration
    assert 'op.create_index("ix_web_authn_credentials_credential_id_b64", "web_authn_credentials", ["credential_id_b64"], unique=True)' in migration
    assert "webauthn==3.0.1" in read("requirements.lock")


def test_passkey_enrollment_authentication_and_telegram_fallback_are_wired():
    routes = read("app/web/auth_routes.py")
    service = read("app/passkeys.py")
    javascript = read("app/web/static/passkeys.js")
    template = read("app/web/templates/login_passkey.html")
    for token in (
        '"/admin/login/passkey/options"',
        '"/admin/login/passkey/verify"',
        '"/admin/login/passkey/fallback"',
        '"/admin/account/passkeys/options"',
        '"/admin/account/passkeys/register"',
        "verify_authentication(",
        "verify_registration(",
        "web_passkey_auth_success",
        "web_passkey_registered",
        "web_passkey_stepup_failed",
    ):
        assert token in routes
    assert "UserVerificationRequirement.REQUIRED" in service
    assert "expected_origin=origin" in service
    assert "credential_current_sign_count" in service
    assert "navigator.credentials.get" in javascript
    assert "navigator.credentials.create" in javascript
    assert "резервний Telegram-код" in template


def test_passkey_verification_mapping_with_library_contract(monkeypatch):
    pytest.importorskip("webauthn")
    from app import passkeys

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kwargs: SimpleNamespace(
            credential_id=b"credential-id",
            credential_public_key=b"public-key",
            sign_count=7,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )
    registered = passkeys.verify_registration(
        credential={"response": {"transports": ["internal"]}},
        challenge_b64=passkeys.b64url_encode(b"challenge"),
        rp_id="example.org",
        origin="https://example.org",
    )
    assert registered.public_key == b"public-key"
    assert registered.sign_count == 7
    assert registered.backed_up is True
    assert registered.transports_json == '["internal"]'

    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **kwargs: SimpleNamespace(
            new_sign_count=8,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )
    authenticated = passkeys.verify_authentication(
        credential={"id": "credential"},
        stored=SimpleNamespace(public_key=b"public-key", sign_count=7),
        challenge_b64=passkeys.b64url_encode(b"challenge"),
        rp_id="example.org",
        origin="https://example.org",
    )
    assert authenticated.new_sign_count == 8
    assert authenticated.backed_up is True


def test_rate_limit_rules_cover_security_sensitive_surfaces():
    expected = {
        ("/admin/login", "POST", ""): "login",
        ("/admin/login/2fa", "POST", ""): "mfa",
        ("/admin/account/passkeys/register", "POST", "application/x-www-form-urlencoded"): "passkey_manage",
        ("/admin/security/accounts/1/reset-password", "POST", ""): "password_reset",
        ("/admin/events/3/scanner", "POST", ""): "qr",
        ("/admin/export/sensitive", "GET", ""): "sensitive_export",
        ("/admin/events/3/participants-sensitive.xlsx", "GET", ""): "sensitive_export",
        ("/admin/events/create", "POST", "multipart/form-data; boundary=x"): "upload",
        ("/event/abc", "GET", ""): "public_share",
        ("/opportunity/10", "GET", ""): "public_share",
    }
    for args, name in expected.items():
        rule = classify_rate_limit(*args)
        assert rule is not None and rule.name == name


def test_sliding_window_limiter_blocks_after_limit():
    async def scenario():
        limiter = SlidingWindowRateLimiter()
        rule = RateLimitRule("test", limit=2, window_seconds=60)
        assert (await limiter.hit("key", rule))[0] is True
        assert (await limiter.hit("key", rule))[0] is True
        allowed, retry_after = await limiter.hit("key", rule)
        assert allowed is False
        assert retry_after >= 1

    asyncio.run(scenario())


def test_csp_is_emitted_with_nonce_and_strict_report_only_policy():
    sent: list[dict] = []

    async def app(scope, receive, send):
        assert scope["state"].get("csp_nonce")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/admin/security-center", "method": "GET", "headers": [], "state": {}}
    asyncio.run(SecurityHeadersMiddleware(app, hsts=True)(scope, receive, send))
    start = next(item for item in sent if item["type"] == "http.response.start")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert "content-security-policy" in headers
    assert "content-security-policy-report-only" in headers
    assert "'unsafe-inline'" in headers["content-security-policy"]
    assert "'nonce-" in headers["content-security-policy-report-only"]
    assert "'unsafe-inline'" not in headers["content-security-policy-report-only"].split("script-src", 1)[1].split(";", 1)[0]
    assert "strict-transport-security" in headers


def test_security_center_permission_is_centralized_and_secret_safe_by_source():
    assert required_web_permission("/admin/security-center", "GET") == "security.manage"
    source = read("app/security_center.py")
    template = read("app/web/templates/security_center.html")
    assert "FIELD_ENCRYPTION_KEY" in source
    assert 'os.getenv("FIELD_ENCRYPTION_KEY"' in source
    assert '"field_key_configured"' in source
    assert "encryption_secret" not in template
    assert "session_secret" not in template
    assert "Значення секретів ніколи не показуються" in template


def test_security_audit_contract_covers_passkeys_and_sensitive_activity():
    routes = read("app/web/auth_routes.py")
    center = read("app/security_center.py")
    media = read("app/web/media_routes.py")
    for action in (
        "web_passkey_registered",
        "web_passkey_auth_success",
        "web_passkey_auth_failed",
        "web_passkey_revoked",
        "web_passkey_fallback_requested",
    ):
        assert action in routes
    assert "web_sensitive_media_view" in media
    assert "web_sensitive_media_download" in media
    assert "SENSITIVE_EXPORT_ACTIONS" in center
    assert "PERMISSION_ACTIONS" in center


def test_runtime_metrics_compute_http_db_export_and_telegram_values():
    metrics = RuntimeMetrics(max_samples=32)
    for value in (10, 20, 30, 40, 100):
        metrics.record_http(path="/admin/dashboard", duration_ms=value, status=200)
    metrics.record_http(path="/admin/analytics/export.pdf", duration_ms=250, status=200)
    metrics.record_http(path="/admin/problem", duration_ms=50, status=500)
    for value in (5, 10, 20):
        metrics.record_db(duration_ms=value)
    metrics.record_telegram_failure()
    snap = metrics.snapshot(window_seconds=900)
    assert snap["http"]["p50_ms"] is not None
    assert snap["http"]["p95_ms"] is not None
    assert snap["http"]["server_error_responses"] == 1
    assert snap["db"]["p95_ms"] is not None
    assert snap["exports"]["samples"] == 1
    assert snap["telegram_api_failures"] == 1


def test_operational_intelligence_has_required_advisory_signals_only():
    source = read("app/governance.py")
    required = (
        "failed_notifications",
        "event_no_reminder",
        "feedback_low",
        "backup_stale",
        "worker_stale",
        "scheduler_stale",
        "login_failures_high",
        "db_pool_pressure",
        "integrity_anomaly",
    )
    for token in required:
        assert token in source
    assert "scan_data_integrity" in source
    assert "runtime_health_snapshot" in source
    # Operational scanner may report/resolve its own advisory rows, but must not
    # modify participant state as a response to those new signals.
    signal_block = source[source.index("# v1.19.0 Observability 2.0"):source.index("# Only after every source")]
    for destructive in ("session.delete(", "DELETE FROM", "permanent_deleted_at =", "wallet_xp ="):
        assert destructive not in signal_block


def test_observability_surface_contains_requested_metrics():
    source = read("app/observability_snapshot.py")
    template = read("app/web/templates/security_center.html")
    metrics = read("app/metrics.py")
    for token in (
        "p50_ms", "p95_ms", "utilization_pct", "oldest_queue_age_seconds",
        "max_lag_seconds", "recent_failed_jobs_24h", "verified_at",
        "storage_megabytes", "telegram_api_failures",
    ):
        assert token in source or token in metrics or token in template

@pytest.mark.asyncio
async def test_operational_scanner_persists_security_and_pool_advisories(db):
    from sqlalchemy import select

    from app.governance import scan_operational_issues
    from app.model_domains import AuditLog, OperationalIssue
    from app.time_utils import clock

    now = clock.storage_utc()
    async with db.session_factory() as session:
        for index in range(5):
            session.add(AuditLog(
                actor_label="test",
                action="web_login_failed",
                entity_type="web_auth",
                details=f"test failure {index}",
                created_at=now,
            ))
        await session.commit()

    async with db.session_factory() as session:
        await scan_operational_issues(
            session,
            backup_max_age_hours=48,
            backup_warning_age_hours=36,
            worker_stale_seconds=120,
            startup_grace_seconds=180,
            db_pool_status={"utilization_pct": 90.0},
            now=now,
        )
        await session.commit()
        issue_types = set((await session.scalars(
            select(OperationalIssue.issue_type).where(OperationalIssue.status == "open")
        )).all())

    assert "login_failures_high" in issue_types
    assert "db_pool_pressure" in issue_types
    assert "worker_stale" in issue_types
