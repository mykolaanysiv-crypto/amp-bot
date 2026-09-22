# AMP XP / «АМПасадори» v1.18.0

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Operational Intelligence & Gamification Governance**.

Key additions: actionable `/admin/operations`, persisted operational issues, gamification rule version history, runtime league thresholds, mandatory reason for system runtime-rule changes, and append-only old/new audit for XP/reward configuration. Historical participant balances are never recalculated automatically when rules change.

Alembic head: `20260921_0014`.

See `SERVER_UPDATE_V1180.md`, `COMMANDS_V1180.txt`, `SECURITY.md`, `HEROKU_DEPLOY.md` and `XP_BALANCE.md`.
