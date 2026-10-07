# AMP XP / «АМПасадори» v1.18.7

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Reproducible Production Baseline**. v1.18.7 freezes the post-v1.18.6 production baseline, adds exact direct dependency locks, blocking dependency audit, documentation/release consistency gates and removes safe deprecation warnings without changing business semantics or the database schema.

## Runtime
- Python 3.13
- Aiogram 3.31.0
- FastAPI 0.142.2 + Jinja2 3.1.6
- SQLAlchemy 2.1.3 async
- PostgreSQL 18 for CI/local baseline/restore verification; SQLite remains supported for local/test scenarios
- Alembic head: `20260925_0015`

## Reproducible dependency layout
- `requirements.in` — human-maintained production intent/ranges.
- `requirements.lock` — exact direct production pins installed by Docker and audited by CI.
- `requirements.txt` — Heroku-compatible wrapper to `requirements.lock`.
- `requirements-dev.in` — human-maintained development/test intent.
- `requirements-dev.lock` — exact direct development pins plus the production lock.
- `requirements-dev.txt` — compatibility wrapper to the development lock.

`python -m scripts.dependency_lock_check` verifies exact pins and lock/input coverage. `python -m scripts.release_consistency_check` verifies version, Alembic head, static cache tokens, release docs, critical runtime files and lock fingerprints.

## v1.18.7 safety baseline
- Python 3.13 aligned across `.python-version`, CI and Docker.
- PostgreSQL 18 aligned for CI, local compose baseline and restore verification using the public ECR mirror.
- Fresh Heroku PGBackup is restore-verified before deployment.
- Post-deploy `/health/ready`, `/health/live` and version smoke remain mandatory.
- Dedicated `FIELD_ENCRYPTION_KEY` remains mandatory in production with previous-key migration support.
- Verified-backup freshness policy remains 36 h warning / 48 h stale by default.
- Server-side admin request-size protection and orphan `MediaAsset` integrity detection remain enabled.
- `pip-audit` is a blocking release gate in v1.18.7.
- No new Alembic migration and no XP/attendance/gamification semantics changes.

See `RELEASE_V1187_UA.md`, `BUILD_MANIFEST_V1187.txt`, `TEST_REPORT_V1187.txt`, `HEROKU_DEPLOY.md`, `SECURITY.md` and `XP_BALANCE.md`.

A ZIP/local test result is not proof that production has been updated. Production v1.18.7 is confirmed only after the GitHub/Heroku deploy gate and health/version smoke pass.
