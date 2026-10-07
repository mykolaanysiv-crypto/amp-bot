# Heroku deployment — АМПасадори v1.18.6

Production is deployed from the repository through GitHub Actions after the full `Production gate` passes on `main`.

## Required GitHub secrets
- `HEROKU_API_KEY`
- `HEROKU_APP_NAME`

## Required production config
`WEB_SESSION_SECRET` must be at least 32 characters. v1.18.6 also requires a separate `FIELD_ENCRYPTION_KEY` of at least 32 characters. The deploy workflow can create the dedicated field key when upgrading from the legacy fallback; the old session key is retained in `FIELD_ENCRYPTION_PREVIOUS_KEYS` for migration compatibility.

Recommended defaults:

```text
BACKUP_UNKNOWN_GRACE_HOURS=24
BACKUP_WARNING_AGE_HOURS=36
BACKUP_MAX_AGE_HOURS=48
WEB_MAX_REQUEST_MB=25
```

## Local/pre-merge checks

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q app scripts migrations tests
python -m scripts.production_preflight
ruff check --select E9,F63,F7,F82 app scripts tests
node tests/js/test_admin_forms.js
pytest -q --ignore=tests/integration
# With TEST_DATABASE_URL/POSTGRES_SMOKE_URL pointed to PostgreSQL 18:
pytest -q tests/integration
python -m scripts.schema_drift_check
```

## Automatic production deploy sequence
1. GitHub Production gate passes.
2. Deploy job verifies Heroku secrets and encryption-key configuration.
3. Fresh Heroku PGBackup is captured.
4. That exact backup is downloaded and restore-verified against an isolated PostgreSQL 18 database.
5. A fresh verified-backup marker is recorded in production.
6. The tested commit is pushed to Heroku.
7. Heroku release process runs startup smoke/Alembic lifecycle gate.
8. GitHub polls `/health/ready`, checks `/health/live`, and verifies version equals `VERSION.txt`.
9. Legacy sensitive fields are re-encrypted with the dedicated field key.

## Expected DB state

```text
Alembic head: 20260925_0015
```

v1.18.6 contains no new migration. Do not run a manual downgrade for this release.

## Rollback note
Code can be rolled back because schema is unchanged, but never remove `FIELD_ENCRYPTION_KEY` or `FIELD_ENCRYPTION_PREVIOUS_KEYS` during rollback. Rotated ciphertext may require both current and previous keys.
