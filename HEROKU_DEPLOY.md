# Heroku deployment — АМПасадори v1.18.0

Production app: `amp-bot-ver-1-5-0`.

Before deploy run compileall, production_preflight, full pytest and `git diff --check`, then capture a Heroku Postgres backup. Deploy through the repository/GitHub production gate. After a successful release verify `alembic current` is `20260921_0014`, web/worker dynos are up, and `/health/ready` returns healthy.

Use `COMMANDS_V1180.txt` for the exact sequence.
