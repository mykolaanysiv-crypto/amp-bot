# AMP XP / «АМПасадори» v1.18.1

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Production Stability & Operational Integrity**.

Key additions: actionable `/admin/operations`, persisted operational issues, gamification rule version history, runtime league thresholds, mandatory reason for system runtime-rule changes, and append-only old/new audit for XP/reward configuration. Historical participant balances are never recalculated automatically when rules change.

Alembic head: `20260921_0014`.

See `SERVER_UPDATE_V1181.md`, `COMMANDS_V1181.txt`, `SECURITY.md`, `HEROKU_DEPLOY.md` and `XP_BALANCE.md`.


Stability fixes: scheduled/locked operational scanning with auto-reopen/auto-resolve audit, grace-aware event reminders, grouped XP anomaly queries, historically versioned league insights, strict league input validation, and cross-platform local launch scripts. No new Alembic revision; database head stays `20260921_0014`. Production deployment is **not** implied by the ZIP or local tests.
