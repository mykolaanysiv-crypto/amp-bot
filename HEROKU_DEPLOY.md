# AMP XP v1.22.0 release candidate deployment review

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


AMP XP v1.22.2 CI hotfix candidate; see RELEASE_V1222_UA.md for scope and verification.


Current release: AMP XP 1.22.3; Alembic head 20261011_0019. Details: RELEASE_V1223_UA.md.

Current release: AMP XP 1.22.5; Alembic head 20261011_0019. Details: RELEASE_V1224_UA.md.

Current release: AMP XP 1.22.6; Alembic head 20261011_0019. Details: RELEASE_V1226_RC_UA.md (release candidate, not production-ready).
