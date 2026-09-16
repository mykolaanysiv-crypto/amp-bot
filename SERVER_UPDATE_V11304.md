# AMP XP / «АМПасадори» v1.13.0.4 — CI Localization & Test Time Hotfix

## Причина релізу

GitHub `Unit and regression tests` після v1.13.0.3 завершувався одним failure:

`tests/test_v190_notification_center.py::test_notification_center_web_and_retry`

Production route вже правильно показував українську назву `Серії участі`, але historical source-inspection test продовжував очікувати англійський рядок `Streak`. Це був застарілий тест, а не regression production-коду.

У тому самому GitHub run Python 3.13 також показував `DeprecationWarning` у `tests/test_v192_smart_opportunities_seasons.py` через `datetime.utcnow()`.

## Виправлення

- `tests/test_v190_notification_center.py`: очікуваний label `Streak` замінено на канонічний `Серії участі`.
- `tests/test_v11303_telegram_web_ux_hotfix.py`: version synchronization більше не pin-ить тільки `1.13.0.3`; test підтримує наступні patch-релізи `1.13.0.x`.
- `tests/test_v192_smart_opportunities_seasons.py`: deadline формується через `clock.storage_utc()`, а локальна календарна дата — через `clock.today_local()`. Це відповідає Error & Time Hardening і не створює deprecated `datetime.utcnow()` warning у цьому тесті.
- Додано `tests/test_v11304_ci_localization_time_hotfix.py`.
- `production_preflight` отримав guard від повторного розходження historical Notification Center test із українською локалізацією та від повернення `datetime.utcnow()` у Smart Opportunities regression.
- Синхронізовано version/cache tokens до `1.13.0.4`.

## Що НЕ змінювалось

- Telegram UX `/start`, `/menu`, `/smart` та винагороди з v1.13.0.3 не змінювались.
- Web runtime і Notification Center production logic не змінювались.
- SQLAlchemy schema залишається **54 таблиці**.
- Нової Alembic migration немає.
- Expected Alembic head: `20260915_0002`.
- Production PostgreSQL не очищати й не пересоздавати.

## Production acceptance

1. `python -m scripts.production_preflight` — PASS.
2. `pytest -q --ignore=tests/integration` у GitHub — PASS, зокрема `test_notification_center_web_and_retry`.
3. PostgreSQL integration — PASS.
4. `python -m scripts.heroku_release` — PASS.
5. `alembic current` — `20260915_0002 (head)`.
6. Після deploy: `web.1` і `worker.1` — `up`; `/health/ready` і `/health/dependencies` — HTTP 200 після startup grace.
