# Heroku deployment — AMP XP v1.20.3

Production deployment is allowed only from GitHub Actions after the full Production Gate passes on `main`.

## Required config
Keep existing `WEB_SESSION_SECRET`, separate `FIELD_ENCRYPTION_KEY`, previous keys when rotating, secure cookies and stable WebAuthn origin/RP configuration. Do not print secret values during verification.

## Local/pre-merge
```bash
python -m pip install -r requirements-dev.lock
python -m pip check
python -m scripts.dependency_lock_check
python -m scripts.build_admin_css
python -m scripts.release_consistency_check
python -m compileall -q app scripts migrations tests
python -m scripts.production_preflight
python -m ruff check --select E9,F63,F7,F82 app scripts tests
node tests/js/test_admin_forms.js
node tests/js/test_app_shell.js
node tests/js/test_experience.js
node tests/js/test_interaction.js
python -m pip_audit -r requirements.lock --progress-spinner=off
python -m pytest -q --ignore=tests/integration
```

PostgreSQL 18 integration and schema drift remain blocking in GitHub CI. Expected Alembic head is `20261010_0018`; **v1.20.3 adds no migration**.

## Automatic production sequence
Dependency/release gates → compile/Ruff/JS/pip-audit/full tests → PostgreSQL 18/schema drift → fresh Heroku PGBackup → isolated restore verification → deploy tested commit → startup/Alembic smoke → health/live/ready/version smoke → verified backup marker.

## UI post-deploy smoke
Complete `UI_VISUAL_CHECKLIST_V1202.md`, especially real account tabs, modal/profile/avatar flows, participant combobox, sidebar/logo/avatar stability, account dropdown, Help Center categories, light/dark contrast, keyboard interaction and mobile overflow.

## Rollback
Preferred rollback: application release rollback to confirmed v1.20.1. Retain Alembic schema `20261010_0018`; do not downgrade DB for this UI-only v1.20.3 rollback.
