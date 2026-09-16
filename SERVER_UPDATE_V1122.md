# AMP XP / «АМПасадори» v1.12.2 — Error & Time Hardening

## Мета релізу

v1.12.2 стабілізує два поперечні шари системи: обробку помилок і бізнес-час. Реліз не додає нову продуктову сутність і не змінює schema; він робить наявні події, schedulers, health, reports та production logs передбачуванішими на midnight/DST і при аваріях.

## 1. Canonical Clock

`app/time_utils.py` тепер є єдиним application boundary для поточного часу:

- `clock.now_utc()` — aware UTC;
- `clock.now_local()` / `clock.today_local()` — aware Europe/Kyiv / local calendar;
- `clock.storage_utc()` / `clock.from_storage_utc()` — adapter для legacy `timestamp without time zone` UTC полів;
- `clock.local_wall()` / `clock.local_wall_to_utc()` — boundary для legacy local-wall scheduled fields;
- `clock.local_period_to_storage_utc()` — DST-safe day/month/report boundaries;
- `clock.seconds_until_local()` — очікування до локального часу через absolute UTC delta.

Production preflight блокує прямі `datetime.utcnow`, `datetime.now` і `date.today` у application/scripts поза canonical Clock.

### Важлива compatibility межа

У v1.12.2 **немає масової зміни типів timestamp колонок PostgreSQL**. Поточні UTC operational timestamps лишаються naive у БД і конвертуються через `clock.storage_utc()`. `Event.starts_at` та сумісні scheduled local-wall поля лишаються local wall time у legacy schema, але для Python business decisions конвертуються в aware UTC. Це мінімізує ризик production data rewrite.

## 2. DST / midnight hardening

- check-in window відкривається/закривається на aware UTC timeline;
- fall-back `fold` підтримується Clock helper; для legacy event field default — `fold=0`;
- birthday scheduler обчислює real seconds до локальних 09:00, а не naive timedelta;
- reports переводять локальні calendar boundaries у naive UTC storage bounds один раз;
- registration «схвалено сьогодні» використовує той самий Europe/Kyiv → UTC boundary;
- season legacy XP backfill більше не порівнює local midnight із UTC transaction timestamps;
- report daily/weekly/monthly buckets локалізують timestamps перед calendar grouping.

## 3. Error hardening

- silent `except Exception: pass` прибрані;
- broad exceptions, які залишилися на process/scheduler/integration boundary, мають recovery/logging semantics замість мовчазного ковтання;
- `scripts.production_preflight` AST-перевіркою не дозволяє повернути silent broad exception;
- critical error paths отримали стабільні error codes.

Приклади кодів:

- `HEARTBEAT_WRITE_FAILED`, `HEARTBEAT_FINAL_WRITE_FAILED`, `SCHEDULER_HEARTBEAT_FAILED`;
- `SCHEDULER_CRASH`, `SCHEDULER_FAILURE_HEARTBEAT_FAILED`;
- `RUNTIME_HEALTH_MONITOR_FAILED`, `RUNTIME_ALERT_SEND_FAILED`;
- `BROADCAST_RESUME_FAILED`, `BROADCAST_RETRY_SCAN_FAILED`;
- `WEB_NOTIFICATION_QUEUE_FAILED`, `VERSION_ANNOUNCEMENT_PREPARE_FAILED`;
- `NOTIFICATION_HEALTH_ALERT_FAILED`, `BACKUP_HEALTH_ALERT_FAILED`;
- entity-open lifecycle codes для events/quests/volunteer tasks.

## 4. Structured logs

JSON log може містити:

- `ts`, `level`, `service`, `logger`, `message`;
- `request_id`, `dyno`;
- `error_code`;
- `context`;
- `exception`;
- `redaction_error` лише якщо сам redaction filter не зміг безпечно обробити record.

`context` проходить bounded JSON conversion. Ключі, що містять token/password/secret та відомі secret names, повертаються як `[REDACTED]`.

## 5. База даних / Alembic

- нової таблиці немає;
- SQLAlchemy metadata: 54 таблиці;
- очікуваний Alembic head: `20260915_0002`;
- v1.12.2 не потребує ручного `alembic upgrade` поза штатним Heroku release process;
- production PostgreSQL не очищати.

## 6. QA

Перевірено у build:

- syntax compile;
- production preflight;
- winter/summer Europe/Kyiv offsets;
- autumn DST repeated local time (`fold`);
- spring DST scheduler wait;
- local midnight/month report boundaries;
- check-in window через DST transition;
- structured `error_code/context` та secret redaction;
- source guard проти direct wall-clock APIs і silent broad exceptions;
- focused v1.12.x regressions.

Full `pytest -q` у поточному sandbox не проходить collection лише через відсутній `aiogram` у цьому audit environment. GitHub Actions із `requirements-dev.txt` і PostgreSQL 16 є authoritative integration gate.

## 7. Production smoke після deploy

1. `web.1` і `worker.1` — `up`.
2. Alembic current — `20260915_0002 (head)`.
3. `/health/ready` — HTTP 200 ready.
4. `/health/dependencies` — HTTP 200 JSON після startup grace; worker/schedulers healthy.
5. Worker log не має repeated scheduler failures; error events, якщо є, мають `error_code`/`context` у JSON logs.
6. Telegram: відкрити подію, перевірити реєстрацію/check-in normal flow.
7. Web Event Cockpit: перевірити check-in state/timestamps.
8. Reports: сформувати поточний місяць і короткий day/week period; calendar boundary має відповідати Europe/Kyiv.
9. Перевірити Notification Center/update announcement і стандартні content views v1.12.1.7.
