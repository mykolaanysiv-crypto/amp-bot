# Оновлення АМПасадори до v1.13.0 на Heroku

Поточна інструкція: `SERVER_UPDATE_V1130.md`.

Рекомендований production flow: GitHub `main` → Production Gate → verified PGBackup → Heroku release → web + worker.

Швидкі команди: `COMMANDS_V1130.txt`.

Важливо: v1.13.0 — architecture-only release, **без schema migration**. Очікуваний Alembic head залишається `20260915_0002`, SQLAlchemy metadata — 54 таблиці. Production PostgreSQL не очищати й не створювати заново.
