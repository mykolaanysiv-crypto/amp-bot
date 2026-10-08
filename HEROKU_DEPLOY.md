# Heroku deployment — AMP XP v1.19.1

Production deployment is allowed only from GitHub Actions after the full Production Gate passes on `main`.

## Required GitHub secrets
- `HEROKU_API_KEY`
- `HEROKU_APP_NAME`

## Required production config
- `WEB_SESSION_SECRET` — random, at least 32 characters.
- `FIELD_ENCRYPTION_KEY` — separate random secret, at least 32 characters.
- `FIELD_ENCRYPTION_PREVIOUS_KEYS` — only while required for safe key rotation.
- `COOKIE_SECURE=1`.

Recommended:

```text
BACKUP_UNKNOWN_GRACE_HOURS=24
BACKUP_WARNING_AGE_HOURS=36
BACKUP_MAX_AGE_HOURS=48
WEB_MAX_REQUEST_MB=25
```

## Passkeys / WebAuthn
For passkeys set the real HTTPS deployment origin:

```text
WEBAUTHN_ORIGIN=https://YOUR_APP_HOST
WEBAUTHN_RP_ID=YOUR_APP_HOST
WEBAUTHN_RP_NAME=АМПасадори / АМП XP
```

`WEBAUTHN_RP_ID` is hostname only: no scheme and no path. It must equal the `WEBAUTHN_ORIGIN` hostname or be its parent domain. Changing RP ID/origin later may make previously registered credentials unusable, so treat these values as stable production identity configuration.

Backward compatibility: if no valid HTTPS WebAuthn origin is configured on a production dyno, the app still starts, passkey enrollment/login is disabled, and Telegram OTP remains the fallback path.

## Local/pre-merge checks

```bash
python -m pip install -r requirements-dev.lock
python -m scripts.dependency_lock_check
python -m scripts.release_consistency_check
python -m compileall -q app scripts migrations tests
python -m scripts.production_preflight
ruff check --select E9,F63,F7,F82 app scripts tests
node tests/js/test_admin_forms.js
pip-audit -r requirements.lock --progress-spinner=off
pip check
pytest -q --ignore=tests/integration
# PostgreSQL 18:
pytest -q tests/integration
python -m scripts.schema_drift_check
```

## Automatic production sequence
1. Dependency/release consistency checks.
2. Compile/preflight/Ruff/JS/pip-audit/pip-check/unit/regression gates.
3. PostgreSQL 18 integration and Alembic previous-production upgrade + downgrade/upgrade roundtrip.
4. Schema-drift gate.
5. Verify required Heroku secrets/config.
6. Capture fresh Heroku PGBackup.
7. Restore and verify the backup in isolated PostgreSQL 18.
8. Deploy the tested commit.
9. Heroku release process performs startup smoke and `alembic upgrade head`.
10. Post-deploy `/health/ready`, `/health/live`, deployed version smoke.
11. Record restore-verified marker only after successful post-deploy smoke.
12. Continue field-encryption rotation workflow as configured.

## Expected DB state

```text
Alembic head: 20261008_0017
Previous production head: 20260925_0015
```

The migration only creates `web_authn_credentials` and is reversible by downgrade to `20260925_0015` when code is also rolled back.

## Rollback
Preferred rollback is application release rollback after confirming whether migration 0016 contains passkey data.

- If no passkeys have been enrolled, code rollback plus Alembic downgrade to `20260925_0015` is safe after a fresh verified backup.
- If passkeys have been enrolled, do not blindly downgrade because it would drop `web_authn_credentials`. Either keep schema 0016 while rolling code back if the older code tolerates the extra table, or export/retain credential records and schedule a controlled downgrade.
- Never remove `FIELD_ENCRYPTION_KEY` or required previous encryption keys during rollback.

After any rollback verify `/health/live`, `/health/ready`, version, web/worker/scheduler state and verified-backup marker.

## v1.19.1 media storage
Deployment does **not** migrate existing database media automatically. Default production behavior remains database-backed unless `MEDIA_STORAGE=s3` is explicitly configured.

S3-compatible configuration (AWS S3 / Cloudflare R2 / Backblaze B2):
- `MEDIA_STORAGE=s3`
- `S3_ENDPOINT=https://...`
- `S3_BUCKET=...`
- `S3_REGION=...` (`auto` is accepted by compatible providers that use it)
- `S3_ACCESS_KEY=...`
- `S3_SECRET_KEY=...`

Never place access/secret keys in logs or release files. Before any switch, require fresh restore-verified PostgreSQL backup, run `dry-run`, `copy`, `verify`, then `switch`. v1.19.1 intentionally retains original database bytes after switch so `rollback` remains possible.
