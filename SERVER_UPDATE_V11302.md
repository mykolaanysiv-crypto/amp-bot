# AMP XP / «АМПасадори» v1.13.0.2 — Startup Import Hotfix

## Причина релізу

GitHub release/startup smoke для v1.13.0.1 дійшов до `import app.main`, після чого впав у новому пакеті `app.handlers.start_flow`:

`ModuleNotFoundError: No module named 'app.handlers.time_utils'`

Після Architecture Completion `start.py` було розділено на вкладений package `app.handlers.start_flow`. Код у `common.py` зберіг relative imports рівня `..`, які були правильні для `app.handlers.start`, але у вкладеному package почали означати `app.handlers.<module>` замість `app.<module>`.

## Виправлення

- `app/handlers/start_flow/common.py`: усі root-app imports змінено з `..` на `...` (`time_utils`, `config`, `observability`, `db`, `keyboards`, `models`, `profile_data`, `services`, `states`, `ui_labels`, `reliability`, `settlements`, `registration_ux`).
- `app/handlers/start_flow/entry.py`: lazy import `gamification` змінено на `...gamification`.
- Додано generic AST guard у `scripts.production_preflight.py`: кожний explicit relative module import у `app/` повинен резолвитись у реальний `.py` module або package `__init__.py`. Це блокує повторення такого runtime-only дефекту ще до release smoke.
- Додано regression suite `tests/test_v11302_startup_import_hotfix.py`.
- Static asset cache tokens у `base.html`, `login.html`, `login_2fa.html` синхронізовано з `1.13.0.2`; preflight тепер контролює це автоматично.

## Що не змінюється

- Business logic і user flows — без функціональних змін.
- SQLAlchemy schema — 54 таблиці.
- Нова Alembic migration — відсутня.
- Production head — `20260915_0002`.
- Compatibility facades v1.13.x зберігаються.
- Production PostgreSQL не очищати і не створювати заново.

## QA

- `python -m compileall -q app scripts tests migrations` — PASS.
- `python -m scripts.production_preflight` — PASS.
- v1.13.0 + v1.13.0.1 + v1.13.0.2 focused architecture/hotfix tests — 20/20 PASS.
- Historical source-layout/static regression bundle, який не потребує локального `aiosqlite`, — 115/115 PASS.
- Static resolver перевірив усі explicit relative module imports у `app/`: unresolved = 0.
- Повні DB/integration tests мають виконуватися в GitHub Actions з `requirements-dev.txt` + PostgreSQL 16.

## Production acceptance

1. GitHub Actions test gate — повністю зелений.
2. `python -m scripts.heroku_release` — PASS, зокрема startup smoke імпортує `app.main` без ModuleNotFoundError.
3. Deploy — зелений.
4. `web.1` і `worker.1` — up.
5. `alembic current` — `20260915_0002 (head)`.
6. `/health/ready` — 200 ready.
7. `/health/dependencies` — 200 після startup grace; worker/schedulers healthy.
8. Telegram `/start` і `/menu` — smoke PASS.
9. Web login/2FA, Dashboard, Event Cockpit, Analytics/Reports — smoke PASS.
