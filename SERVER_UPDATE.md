# Оновлення АМПасадори до v1.12.2 на Heroku

Поточна інструкція: `SERVER_UPDATE_V1122.md`.

Рекомендований production flow: GitHub `main` → Production Gate → verified PGBackup → Heroku release → web + worker.

Швидкі команди: `COMMANDS_V1122.txt`.

Важливо: v1.12.2 **не додає schema migration**. Очікуваний Alembic head залишається `20260915_0002`, metadata — 54 таблиці. Production PostgreSQL не очищати й не створювати заново.
