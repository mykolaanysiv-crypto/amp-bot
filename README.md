# AMP XP / «АМПасадори» v1.14.0 — Donations XP + Ambassador Cabinets

v1.14.0 додає автоматичний XP за донати (1 XP = 5 грн) з retroactive backfill, кабінет АМПасадора, напрями відповідальності, звітність із фото та QR події для зареєстрованих АМПасадорів.

## Production

- PostgreSQL schema: 54 таблиці.
- Alembic head: `20260917_0003`.
- Release flow: GitHub Production Gate → verified backup → Heroku release/web/worker.
- Перед deploy рекомендований ручний Heroku PGBackup.

Деталі: `SERVER_UPDATE_V1131.md`, `TEST_REPORT_V1131.txt`, `COMMANDS_V1131.txt`.
