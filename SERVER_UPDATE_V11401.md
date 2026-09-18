# SERVER UPDATE — AMP XP / «АМПасадори» v1.14.0.1

## Release Schema Order Hotfix

### Причина
Production release v68 зупинився до застосування `20260917_0003`: `bootstrap_defaults()` виконав ORM `SELECT users...`, а модель `User` уже містила `ambassador_responsibility`. PostgreSQL production ще залишався на `20260915_0002`, тому asyncpg повернув `UndefinedColumnError`.

### Виправлення
Release lifecycle змінено з:

`db.init() -> bootstrap_defaults() -> Alembic -> web lifespan`

на:

`db.init() -> Alembic upgrade head -> bootstrap_defaults() -> web lifespan`.

Таким чином жоден ORM bootstrap-запит не читає нові mapped columns до завершення additive schema migration.

### Захист від повторення
- `production_preflight` перевіряє порядок чотирьох release phases.
- historical production-stability regression оновлений під schema-first bootstrap.
- додано `tests/test_v11401_release_schema_order.py`.
- historical v1.14.0 test більше не pin-ить patch version.

### Schema
Нова migration НЕ додається. Очікуваний production head після успішного deploy: `20260917_0003`.
Функціональність v1.14.0 — donation XP, Ambassador Cabinets, responsibility, reports, event QR — не змінена.
