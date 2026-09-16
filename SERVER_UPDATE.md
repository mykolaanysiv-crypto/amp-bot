# Оновлення АМПасадори до v1.12.1.7 на Heroku

Поточна інструкція: `SERVER_UPDATE_V11217.md`.

Рекомендований production flow: GitHub `main` → Production Gate → verified PGBackup → Heroku release → web + worker.

Швидкі команди: `COMMANDS_V11217.txt`.

Важливо: v1.12.1.7 додає additive Alembic migration `20260915_0002` і таблицю `content_views`; production PostgreSQL не очищати й не створювати заново.
