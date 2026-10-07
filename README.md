# AMP XP / «АМПасадори» v1.19.0

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Security & Observability 2.0**. v1.19.0 builds on the reproducible v1.18.7 baseline and adds staff passkeys/WebAuthn, a centralized Security Center, server-side rate limiting, staged Content Security Policy and expanded operational telemetry without changing participant, XP, attendance or gamification semantics.

## Runtime
- Python 3.13
- Aiogram 3.31.0
- FastAPI 0.142.2 + Jinja2 3.1.6
- SQLAlchemy async
- PostgreSQL 18 baseline for CI/local/restore verification
- Alembic head: `20261007_0016`

## Security & Observability 2.0
- WebAuthn/passkeys for authenticated staff; user verification required.
- Passkey is used as the preferred second factor when configured; Telegram OTP remains fallback/recovery and remains mandatory fallback for superadmin policy.
- Passkey enrollment requires the current password as step-up confirmation.
- Central Security Center for login failures, locks, active/stale sessions, MFA/passkey coverage, sensitive audit activity, encryption configuration and operational telemetry.
- Server-side rate limits for login/MFA/passkey management/password reset/QR/sensitive exports/uploads/public share routes.
- Enforced CSP origin allow-list plus nonce-first Report-Only policy for migration away from legacy inline handlers.
- Bounded in-process HTTP/DB/export/Telegram telemetry with no request bodies, SQL text, parameters or participant identifiers.
- Notification queue age/failures, DB pool utilization, scheduler lag/failures, verified backup age, media storage usage.
- Operational advisory issues for stale worker/schedulers, failed notifications, old backup, missing reminders, low feedback, login failure spikes, DB pool pressure and high-risk integrity anomalies.
- No automatic destructive response to operational alerts.

## Passkey production configuration
Set an HTTPS origin matching the actual production host:

```text
WEBAUTHN_ORIGIN=https://YOUR_APP_HOST
WEBAUTHN_RP_ID=YOUR_APP_HOST
WEBAUTHN_RP_NAME=АМПасадори / АМП XP
```

If production has no valid HTTPS WebAuthn origin, the application remains backward compatible: passkey enrollment/authentication is disabled and existing Telegram OTP flow remains available. Secrets are never displayed in Security Center.

## Dependencies
- `requirements.in` — production intent.
- `requirements.lock` — exact direct production pins; includes `webauthn==3.0.1` and `cryptography==50.0.2`.
- `requirements-dev.lock` — exact direct development/test pins plus production lock.
- `pip-audit` remains a blocking CI gate.

## Database
v1.19.0 adds one additive migration:

```text
20260925_0015 -> 20261007_0016
```

It creates `web_authn_credentials`. No participant/XP/attendance tables are altered.

See `RELEASE_V1190_UA.md`, `AUDIT_V1190_BASELINE_UA.md`, `BUILD_MANIFEST_V1190.txt`, `TEST_REPORT_V1190.txt`, `COMMANDS_V1190.txt`, `HEROKU_DEPLOY.md` and `SECURITY.md`.

A ZIP or local test result is not proof of production. v1.19.0 becomes production only after green GitHub production gates, restore-verified backup, successful Heroku release and post-deploy health/version verification.
