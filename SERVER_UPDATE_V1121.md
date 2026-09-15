# AMP XP / «АМПасадори» v1.12.1 — Production Stability Gate

v1.12.1 — стабілізаційний реліз поверх v1.12.0.1. Зовнішня продуктова поведінка не змінюється; головна мета — не допустити production-реліз, якщо застосунок не проходить реальний lifecycle запуску.

## 1. Реальний release/startup smoke

`python -m scripts.heroku_release` тепер запускає production lifecycle smoke у фактичному порядку:

`db.init() → bootstrap_defaults() → Alembic upgrade head → FastAPI lifespan → import worker`.

Smoke використовує `AMP_STARTUP_SMOKE=1`, тому не надсилає учасникам version broadcasts і не запускає довготривалі фонові задачі. Будь-який `NameError`, import regression, Alembic failure, bootstrap failure або web lifespan failure завершує release phase з ненульовим кодом, і Heroku не промотує web/worker нового релізу.

## 2. PostgreSQL 16 CI gate

GitHub Actions на кожний push/PR запускає PostgreSQL 16 service і проходить:

- compile;
- production preflight;
- regression tests;
- PostgreSQL integration tests;
- реальний `python -m scripts.heroku_release` проти PostgreSQL 16;
- перевірку Alembic head.

Job `deploy` має `needs: test` і працює лише для `main`. Рекомендований production flow: GitHub `main` → CI PASS → deploy. Прямий ручний `git push heroku` слід залишити тільки як emergency path, бо його не може заблокувати сам код репозиторію без зовнішніх налаштувань доступу/branch protection.

## 3. Розділені health endpoints

- `/health/live` — процес FastAPI живий; зовнішніх залежностей не перевіряє.
- `/health/ready` — startup завершений, БД відповідає, Alembic на head; при проблемі повертає HTTP 503.
- `/health/dependencies` — БД, pool telemetry, Alembic, worker heartbeat і всі scheduler heartbeat; degraded стан повертає HTTP 503.

Відповіді мають `Cache-Control: no-store`.

## 4. PostgreSQL pool limits

Нові Config Vars:

- `DB_POOL_SIZE=3`
- `DB_MAX_OVERFLOW=2`
- `DB_POOL_TIMEOUT=10`
- `DB_POOL_RECYCLE=300`

Ліміти застосовуються лише до PostgreSQL. `/health/dependencies` показує неперсональні pool metrics: size / checked-in / checked-out / overflow / utilization.

## 5. Worker heartbeat

Worker кожні `WORKER_HEARTBEAT_SECONDS` записує heartbeat у наявну таблицю `system_settings`. За замовчуванням:

- interval: 30 s;
- stale: 120 s.

Web process читає цей marker, тому може визначити смерть Telegram worker навіть якщо сам worker уже не здатний надіслати alarm.

## 6. Scheduler supervisor + alarm

Кожний нескінченний scheduler запускається через supervisor. Якщо coroutine:

- аварійно падає;
- або несподівано повертається,

supervisor записує статус `failed`, надсилає прямий Telegram alarm суперадмінам і перезапускає scheduler після короткої затримки.

Додатково web health monitor виявляє stale heartbeat scheduler і надсилає rate-limited alarm навіть при смерті worker. Повтор для одного incident за замовчуванням — не частіше 1 раз/год.

## 7. Схема БД

Нових таблиць немає. Heartbeat/alert markers зберігаються в існуючій `system_settings`, тому schema count залишається 53 і окрема data migration не потрібна.
