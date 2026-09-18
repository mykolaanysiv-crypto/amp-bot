# AMP XP / «АМПасадори» v1.14.0.2 — Telegram Profile Import Hotfix

v1.14.0.2 виправляє відкриття «👤 Мій профіль» у Telegram після додавання напряму відповідальності АМПасадора. Причина — `UserRole` використовувався у profile handler, але не був явно імпортований після архітектурного split.

## Production

- PostgreSQL schema: без змін від v1.14.0.1.
- Alembic head: `20260917_0003`.
- Release flow: GitHub Production Gate → verified backup → Heroku release/web/worker.
- Нова міграція для цього hotfix не потрібна.

Деталі: `SERVER_UPDATE_V11402.md`, `TEST_REPORT_V11402.txt`, `COMMANDS_V11402.txt`.
