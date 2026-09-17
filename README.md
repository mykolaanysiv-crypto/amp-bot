# AMP XP / «АМПасадори» v1.13.1 — Profile, Badges & Analytics UX

v1.13.1 — функціональне UX-оновлення поверх Architecture Completion v1.13.x. Виправляє XP у профілі Telegram, додає повний каталог/мої бейджі та автоматичні badge notifications, індикатор суперсерії біля ПІБ, вирівнює web layout/top search і додає інтерактивний drill-down агрегованої аналітики для суперадміністратора.

## Production

- PostgreSQL schema: 54 таблиці.
- Alembic head: `20260915_0002`.
- Release flow: GitHub Production Gate → verified backup → Heroku release/web/worker.
- Перед deploy рекомендований ручний Heroku PGBackup.

Деталі: `SERVER_UPDATE_V1131.md`, `TEST_REPORT_V1131.txt`, `COMMANDS_V1131.txt`.
