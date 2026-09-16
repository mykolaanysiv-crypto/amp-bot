# AMP XP / «АМПасадори» v1.13.0 — Architecture Completion

## Мета релізу

Завершити великий refactor без зміни користувацьких контрактів і production data model. Основні monolith-файли v1.12.2 розділені на composition roots, domain modules і explicit compatibility facades.

## 1. FastAPI application factory

Canonical web entry point: `app/web/factory.py` → `create_app()`.

`run_web.py` запускає:

```text
app.web.factory:create_app (factory=True)
```

`app/web/app.py` лишився мінімальним facade із `app = create_app()` для сумісності старих import paths і release/startup tooling протягом 1–2 релізів.

Web responsibilities розкладені так:
- `dependencies.py` — shared web dependencies/helpers;
- `lifespan.py` — startup/shutdown runtime;
- `health_routes.py` — `/health`, `/health/live`, `/health/ready`, `/health/dependencies`;
- `auth_routes.py` — login/2FA/account security;
- `media_routes.py` — protected media/files;
- `broadcast_runtime.py` — broadcast delivery/runtime helpers;
- `factory.py` — лише composition/middleware/router registration.

## 2. Event web routes

Старий великий `app/web/routes/events.py` замінено facade-модулем. Canonical routes знаходяться в `app/web/event_routes/`:
- `overview.py`;
- `participants.py`;
- `operations.py`;
- `mutations.py`;
- `telegram_scanner.py`;
- `scanner_common.py`;
- `public.py`;
- `context.py`.

Функціональні handler bodies перенесені без зміни бізнес-логіки.

## 3. Analytics / Reporting

`app/analytics.py` тепер compatibility facade над:
- `app/analytics_modules/core.py`;
- `app/analytics_modules/exports.py`.

`app/reports.py` тепер facade над:
- `app/reporting/periods.py`;
- `app/reporting/builder.py`;
- `app/reporting/exports.py`.

Публічні функції старих import paths збережені на transition window.

## 4. Models by domain

Canonical SQLAlchemy definitions перенесені в `app/model_domains/`:
- `base.py`;
- `identity.py`;
- `gamification.py`;
- `events.py`;
- `engagement.py`;
- `donations.py`;
- `communications.py`.

`app/models.py` експортує їх явно як compatibility facade. Порівняння metadata до/після split підтвердило ідентичну структуру: **54 таблиці**, без нового Alembic revision.

## 5. Telegram start / runtime / jobs

`app/handlers/start.py` → facade, canonical `/start` і registration flow у `app/handlers/start_flow/`.

`app/main.py` скорочено до orchestration:
1. settings/data dir;
2. DB init/bootstrap;
3. bot creation/profile;
4. dispatcher composition;
5. worker heartbeat;
6. 13 scheduler supervisors;
7. polling/shutdown.

Telegram middleware знаходяться в `app/telegram_middleware.py`, dispatcher/profile setup — в `app/bot_runtime.py`.

Усі 13 background scheduler винесені в `app/jobs/` і збираються через `scheduler_factories()` у `app/jobs/registry.py`.

## 6. Wildcard imports

У `app/` немає `from ... import *`. Domain services, handlers, web routes і compatibility facades використовують explicit imports/exports. Це прибирає приховані залежності, які раніше могли проявлятися як runtime NameError після refactor.

## 7. Compatibility window

На 1–2 наступні релізи залишені facades для:
- `app.models`;
- `app.analytics`;
- `app.reports`;
- `app.web.app`;
- `app.web.routes.events`;
- `app.handlers.start`;
- `app.services` та split Telegram admin/participant facades, які вже існували з v1.12.x.

Новий код має використовувати canonical domain modules. Після міграції internal/external imports facades можна видалити окремим cleanup-релізом із regression gate.

## 8. Production guards

`python -m scripts.production_preflight` тепер додатково перевіряє:
- `create_app()` та Uvicorn factory mode;
- canonical split directories/modules;
- максимальний розмір compatibility/composition modules;
- повну відсутність wildcard imports у `app/`;
- health JSON boundary після перенесення routes;
- model facade / Alembic continuity;
- усі Error & Time Hardening gates v1.12.2.

Startup smoke створює app через `app.web.factory.create_app()` і окремо імпортує `app.web.app` як compatibility-regression check.

## 9. Schema / migration

v1.13.0 **не додає schema migration**.

Очікується:
- SQLAlchemy tables: `54`;
- Alembic head: `20260915_0002`;
- production DB rewrite: **не потрібен**.

## 10. Post-deploy acceptance

Після зеленого GitHub Production Gate перевірити:
- `web.1` і `worker.1` — `up`;
- `alembic current` → `20260915_0002 (head)`;
- `/health/ready` → HTTP 200 / ready;
- `/health/dependencies` → HTTP 200 після startup grace;
- worker + 13 schedulers healthy;
- Telegram `/start`, Home, Події, Квести, Волонтерство;
- Web login/2FA, Dashboard, Події/Event Cockpit, Analytics, Reports;
- Notification Center + Content Views;
- відсутність repeated import/startup/scheduler errors у logs.
