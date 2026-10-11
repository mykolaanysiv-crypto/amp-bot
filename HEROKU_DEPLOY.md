# Heroku deployment — AMP XP v1.21.0

v1.21.0 is a code/UI release based on the confirmed production schema. It adds no Alembic migration.

Expected production baseline:
- Python 3.13
- PostgreSQL 18
- Alembic head `20261010_0018`

Deployment remains GitHub-main-workflow driven. Do not bypass a failed CI/security/backup gate with a manual Heroku push.

Required pre-deploy gates:
- dependency lock consistency
- release consistency
- compileall
- production preflight
- Ruff
- pip-audit
- pip check
- full pytest
- PostgreSQL 18 integration
- schema drift
- backup capture + real restore verification

Post-deploy checks:
- `/health/live`
- `/health/ready`
- version = `1.21.0`
- `alembic current` = `20261010_0018`
- verified backup marker
- web + worker healthy
- manual role/navigation and visual smoke

Preferred rollback is a Heroku code release rollback to the last confirmed stable release. Keep schema `20261010_0018`; v1.21.0 does not require an Alembic downgrade.
