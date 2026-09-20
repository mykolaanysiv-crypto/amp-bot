# АМП XP / «АМПасадори» v1.17.1 — Core Cleanup & Alembic Full Adoption

## 1. Alembic — єдине джерело production schema

`Database.init()` більше не виконує `create_all`, legacy `_migrate_v10_to_v11`, runtime `CREATE INDEX` або інші schema/data migrations. Він лише відкриває реальне з'єднання, застосовує SQLite runtime PRAGMA і виконує `SELECT 1`.

Release lifecycle змінено на:

`Alembic upgrade head → db.init() → bootstrap_defaults() → FastAPI lifespan → import worker`.

## 2. Frozen bootstrap baseline

Revision `20260915_0001` тепер містить frozen Alembic schema bootstrap для чистої БД. Він використовує explicit `op.create_table` / `op.create_index`, а не runtime ORM `create_all`.

Для вже Alembic-managed production DB цей historical revision повторно не виконується.

## 3. Новий head

`20260920_0009_alembic_full_adoption` поверх `20260920_0008`.

Revision переносить останній idempotent legacy outbox backfill (`notification_deliveries → notifications`) з application startup у Alembic. Downgrade data-safe: не видаляє вже перенесені/оброблені повідомлення.

## 4. Schema drift gate

Додано `python -m scripts.schema_drift_check`.

CI порівнює фактичну PostgreSQL schema на Alembic head з `app.model_domains.Base.metadata`. Якщо розробник додасть/змінить mapped table/column/index без revision — Production Gate падає до deploy.

## 5. Migration QA у CI

PostgreSQL 16 перевіряє:

- previous production head `20260920_0008 → head`;
- latest revision `head → downgrade 0008 → head`;
- real release/startup smoke;
- `alembic current`;
- model/schema drift.

## 6. Architecture cleanup

Retired transitional facades видалені:

- `app.models` → `app.model_domains`;
- `app.services` → `app.domain_services`;
- `app.analytics` → `app.analytics_modules`;
- `app.reports` → `app.reporting`;
- `app.web.app` → `app.web.factory:create_app`;
- `app.web.routes.events` → `app.web.event_routes`;
- `app.handlers.start` → `app.handlers.start_flow`.

`production_preflight` блокує повторне створення цих facades або імпортів на них.

## 7. Production acceptance

Після deploy:

1. `alembic current` → `20260920_0009 (head)`;
2. `/health/ready` → 200;
3. `/health/dependencies` → 200 після startup grace;
4. `web.1` і `worker.1` → up;
5. немає startup/import/schema errors у логах.
