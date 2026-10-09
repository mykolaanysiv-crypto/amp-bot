# Heroku deployment — AMP XP v1.20.0

Production deployment is allowed only from GitHub Actions after the full Production Gate passes on `main`.

## Required GitHub secrets
- `HEROKU_API_KEY`
- `HEROKU_APP_NAME`

## Required production security config
- `WEB_SESSION_SECRET`
- `FIELD_ENCRYPTION_KEY` — separate from session secret
- `FIELD_ENCRYPTION_PREVIOUS_KEYS` only when required for rotation
- `COOKIE_SECURE=1`
- stable WebAuthn `WEBAUTHN_ORIGIN`, `WEBAUTHN_RP_ID`, `WEBAUTHN_RP_NAME` when passkeys are enabled.

## Local/pre-merge checks

```bash
python -m pip install -r requirements-dev.lock
python -m scripts.dependency_lock_check
python -m scripts.build_admin_css
python -m scripts.release_consistency_check
python -m compileall -q app scripts migrations tests
python -m scripts.production_preflight
python -m ruff check --select E9,F63,F7,F82 app scripts tests
node tests/js/test_admin_forms.js
node tests/js/test_app_shell.js
python -m pip_audit -r requirements.lock --progress-spinner=off
python -m pip check
python -m pytest -q --ignore=tests/integration
```

PostgreSQL 18 integration and `python -m scripts.schema_drift_check` remain mandatory in GitHub CI. v1.20.0 has no new Alembic revision; expected head is `20261008_0017`.

## Automatic production sequence
1. dependency/release consistency;
2. CSS bundle consistency, compile, preflight, Ruff, JS smoke, pip-audit, pip-check;
3. full unit/regression suite;
4. PostgreSQL 18 integration and Alembic compatibility gates;
5. schema drift rejection;
6. fresh Heroku PGBackup;
7. restore verification in isolated PostgreSQL 18;
8. deploy tested commit;
9. release startup smoke / `alembic upgrade head`;
10. `/health/ready`, `/health/live`, deployed version smoke;
11. verified backup marker only after successful post-deploy checks.

## Expected DB state

```text
Alembic head: 20261008_0017
No v1.20.0 schema migration
```

## UI post-deploy smoke
- open `/admin/dashboard` on desktop and mobile widths;
- collapse/expand sidebar and reload: preference must persist;
- mobile hamburger: backdrop, ESC, focus trap and focus return;
- verify global search shortcut `/`;
- login, Telegram OTP and passkey fallback;
- Security Center and Media Integrity Center;
- critical forms and destructive actions;
- light/dark theme;
- keyboard-only navigation and visible focus.

Use `UI_VISUAL_CHECKLIST_V1200.md` before tagging the release.

## Rollback
Preferred rollback is application release rollback to the last confirmed v1.19.1 release. v1.20.0 adds no database migration, so do not downgrade Alembic for a pure UI rollback. Continue to protect `FIELD_ENCRYPTION_KEY`, previous encryption keys and existing media storage configuration.

## Media storage
Do not run database→S3 `copy`/`switch` as part of this UI release. v1.19.1 migration tooling remains a separate, explicitly reviewed operational process.
