# AMP XP / «АМПасадори» v1.17.1 — Core Cleanup & Alembic Full Adoption

v1.17.1 завершує технічний перехід на canonical architecture та робить Alembic єдиним production-механізмом зміни схеми БД.

## Основне

- `Database.init()` більше не створює таблиці, колонки чи індекси і не виконує legacy `_migrate_v10_to_v11`;
- release-order: `Alembic upgrade head → db.init() → bootstrap_defaults() → FastAPI lifespan`;
- Alembic baseline містить frozen schema bootstrap для чистої БД;
- новий head: `20260920_0009`;
- CI перевіряє `previous production head → upgrade head`, latest `downgrade → upgrade`, PostgreSQL 16 startup smoke та model/schema drift;
- `scripts/schema_drift_check.py` блокує модельну зміну без Alembic revision;
- retired compatibility facades видалені: `app.models`, `app.services`, `app.analytics`, `app.reports`, `app.web.app`, `app.web.routes.events`, `app.handlers.start`;
- production код використовує `model_domains`, `domain_services`, `analytics_modules`, `reporting`, `event_routes`, `start_flow` напряму.

## Production

- Перед deploy: verified PostgreSQL backup.
- Deploy: GitHub Production Gate → Heroku release.
- Після deploy: `alembic current` має показати `20260920_0009 (head)`.
- Не запускайте ручні DDL-зміни production БД.

Деталі: `SERVER_UPDATE_V1171.md`, `TEST_REPORT_V1171.txt`, `HEROKU_DEPLOY.md`.
