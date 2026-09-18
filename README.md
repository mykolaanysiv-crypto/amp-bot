# AMP XP / «АМПасадори» v1.14.0.1 — Release Schema Order Hotfix

v1.14.0.1 зберігає функціональність v1.14.0 і виправляє порядок release lifecycle: Alembic `20260917_0003` застосовується до ORM bootstrap, тому нові mapped-колонки не читаються до появи в PostgreSQL.

## Production

- PostgreSQL schema: 54 таблиці.
- Alembic head: `20260917_0003`.
- Release flow: GitHub Production Gate → verified backup → Heroku release/web/worker.
- Перед deploy рекомендований ручний Heroku PGBackup.

Деталі: `SERVER_UPDATE_V11401.md`, `TEST_REPORT_V11401.txt`, `COMMANDS_V11401.txt`.
