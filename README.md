# AMP XP / «АМПасадори» v1.18.6

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Platform Hardening**. v1.18.6 strengthens CI/CD, backup verification, encryption-key separation, upload protection and data-integrity checks without changing the production database schema.

## Runtime
- Python 3.13
- Aiogram 3
- FastAPI + Jinja2
- SQLAlchemy 2 async
- PostgreSQL 18 production/backup verification; SQLite remains supported for local/test scenarios
- Alembic head: `20260925_0015`

## v1.18.6 highlights
- Python 3.13 aligned across `.python-version`, CI and Docker.
- Fresh Heroku PGBackup is restore-verified on isolated PostgreSQL 18 before deployment.
- Post-deploy `/health/ready`, `/health/live` and version smoke.
- Dedicated `FIELD_ENCRYPTION_KEY` required in Heroku production; legacy fallback ciphertext remains readable through key rotation support.
- Verified-backup freshness policy: warning after 36 h, stale after 48 h by default.
- Server-side admin request limit (`WEB_MAX_REQUEST_MB`, default 25 MB).
- Data Integrity detects orphan database media without deleting it automatically.
- CI runs Python compile/preflight, Ruff critical checks, JavaScript smoke, pytest, PostgreSQL integration/Alembic gates and schema drift checks; `pip-audit` is advisory in this release.

See `RELEASE_V1186_UA.md`, `HEROKU_DEPLOY.md`, `SECURITY.md` and `XP_BALANCE.md`.

A ZIP/local test result is not proof that production has already been updated. Production version is confirmed only after the GitHub/Heroku deploy gate and health/version smoke pass.
