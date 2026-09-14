# Heroku deploy — AMP XP v1.10.3

1. Зробіть backup production PostgreSQL перед релізом.
2. Розпакуйте v1.10.3 у чисту робочу директорію.
3. Встановіть залежності з `requirements.txt`.
4. Перевірте `BOT_TOKEN`, `DATABASE_URL`, `WEB_SESSION_SECRET`, `TIMEZONE=Europe/Kyiv` та інші чинні Config Vars.
5. Виконайте `python -m compileall -q app scripts tests` і `pytest -q`.
6. Перевірте `VERSION.txt = 1.10.3`.
7. Commit: `AMP XP v1.10.3 data integrity and data quality`.
8. Push у Heroku.
9. Під час startup SQLAlchemy idempotently створить нову таблицю `settlement_references`; bootstrap нормалізує відомі aliases населених пунктів.
10. `/health` має показати `1.10.3`.
11. Виконайте smoke checklist із `SERVER_UPDATE_V1103.md`.

Rollback коду можливий звичайним Heroku rollback. Нова additive таблиця не заважає v1.10.2, але перед rollback production data все одно рекомендовано мати backup.
