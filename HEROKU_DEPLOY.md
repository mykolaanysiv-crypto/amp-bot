# Heroku deployment — АМПасадори v1.18.7

Production is deployed from GitHub Actions only after the full `Production gate` passes on `main`.

## Required GitHub secrets
- `HEROKU_API_KEY`
- `HEROKU_APP_NAME`

## Required production config
- `WEB_SESSION_SECRET` — at least 32 characters.
- `FIELD_ENCRYPTION_KEY` — separate secret, at least 32 characters.
- `FIELD_ENCRYPTION_PREVIOUS_KEYS` — retained as needed for safe key rotation/migration.

Recommended defaults:

```text
BACKUP_UNKNOWN_GRACE_HOURS=24
BACKUP_WARNING_AGE_HOURS=36
BACKUP_MAX_AGE_HOURS=48
WEB_MAX_REQUEST_MB=25
```

## Reproducible dependency files
Production install: `requirements.lock` via `requirements.txt`.
CI/dev install: `requirements-dev.lock` via `requirements-dev.txt`.
Do not edit a lock without updating the corresponding `.in` file and release manifest.

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
# With TEST_DATABASE_URL/POSTGRES_SMOKE_URL pointed to PostgreSQL 18:
pytest -q tests/integration
python -m scripts.schema_drift_check
```

## Automatic production deploy sequence
1. Dependency lock and release/documentation consistency gates pass.
2. Compile/preflight/Ruff/JS/pip-audit/pip-check/unit/regression/PostgreSQL/Alembic/schema-drift gates pass.
3. Deploy job verifies Heroku secrets and encryption-key configuration.
4. Fresh Heroku PGBackup is captured.
5. That backup is downloaded and restore-verified against isolated PostgreSQL 18.
6. The tested commit is pushed to Heroku.
7. Heroku release process runs startup smoke and Alembic lifecycle gate.
8. GitHub polls `/health/ready`, checks `/health/live`, and verifies the deployed version equals `VERSION.txt`.
9. Only after successful post-deploy smoke is the fresh restore-verified marker recorded.
10. Legacy sensitive fields are re-encrypted with the dedicated field key.

## Expected DB state

```text
Alembic head: 20260925_0015
```

v1.18.7 contains no new migration. Do not manually alter production schema.

## Rollback
Because schema is unchanged, code rollback is supported. Roll back to the last confirmed production commit/release, but never remove `FIELD_ENCRYPTION_KEY` or required previous keys. After rollback verify `/health/live`, `/health/ready`, version, worker/scheduler health and backup marker.
