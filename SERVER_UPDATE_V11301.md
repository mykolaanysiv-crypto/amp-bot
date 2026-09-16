# AMP XP / «АМПасадори» v1.13.0.1 — Architecture CI Compatibility Hotfix

## Призначення

v1.13.0.1 — patch-реліз поверх v1.13.0 Architecture Completion. Він виправляє GitHub regression suite після того, як canonical implementation було рознесено з історичних монолітних файлів у domain packages.

Важливо: це **не rollback архітектури** і не повернення реалізації в compatibility facades. Тести оновлено так, щоб перевіряти фактичні canonical modules.

## Що було причиною CI failure

Після v1.13.0 низка historical source-inspection tests продовжувала читати старі файли:

- `app/main.py` замість `app/bot_runtime.py` + `app/jobs/*`;
- `app/models.py` замість `app/model_domains/*`;
- `app/web/app.py` замість `app/web/factory.py`, `auth_routes.py`, `broadcast_runtime.py`, `lifespan.py`;
- `app/web/routes/events.py` замість `app/web/event_routes/*`;
- `app/analytics.py` замість `app/analytics_modules/*`;
- `app/reports.py` замість `app/reporting/*`;
- `app/handlers/start.py` замість `app/handlers/start_flow/*`.

Через це функціональність існувала, але tests шукали рядки у compatibility facade і давали false-negative.

## Виправлення

### 1. Canonical test source layout

Додано `tests/source_layout.py` з централізованими helpers:

- `main_source()`;
- `start_source()`;
- `web_app_source()`;
- `event_routes_source()`;
- `models_source()`;
- `analytics_source()`;
- `reports_source()`;
- `broadcast_runtime_source()`.

Це прибирає знання про фізичний layout із десятків historical tests. Наступний refactor потребуватиме оновити одну карту, а не багато тестів.

### 2. Historical regression suite

Оновлено 32 checks, що впали у GitHub після Architecture Completion. Assertions залишилися змістовними — змінилося лише джерело canonical implementation.

### 3. Event scanner / FastAPI regression

`test_event_scanner_has_no_csrf_body_parameter` тепер AST-перевіряє `app/web/event_routes/operations.py`.

Загальний guard для FastAPI body params тепер сканує обидва каталоги:

- `app/web/routes/`;
- `app/web/event_routes/`.

### 4. Notification Center allowlist

Immediate Web 2FA Telegram delivery після split знаходиться в `app/web/auth_routes.py`. Regression allowlist перенесено зі старого `app/web/app.py` на фактичний canonical path.

Дозволені direct `bot.send_message` залишаються тільки у:

- canonical Telegram delivery implementation;
- immediate Web 2FA;
- runtime-health emergency channel.

Business notifications надалі мають використовувати Notification Center/outbox.

### 5. Version update runtime tests

Distributed version lock, per-user outbox dedupe і startup ordering тепер перевіряються у:

- `app/web/broadcast_runtime.py`;
- `app/web/lifespan.py`.

Тести більше не вимагають, щоб ці functions знаходились у `app/web/app.py`.

### 6. Version tests

Historical v1.13.0 Architecture Completion test більше не pin-ить точний `1.13.0`; він перевіряє continuity гілки `1.13.x`. Exact version v1.13.0.1 контролюється окремим hotfix test.

## Runtime та БД

- Business logic: без змін.
- SQLAlchemy metadata: **54 таблиці**.
- Нова Alembic migration: **відсутня**.
- Production head: `20260915_0002`.
- Production PostgreSQL не очищати й не створювати заново.
- Compatibility facades з v1.13.0 залишаються на заплановані 1–2 релізи.

## Локальна QA-перевірка

Підтверджено у build environment:

- `python -m compileall -q app scripts tests migrations` — PASS;
- `python -m scripts.production_preflight` — PASS (`Production preflight OK for AMP v1.13.0.1`);
- `tests/test_v11301_ci_compat_hotfix.py` + v1.13.0 architecture suite — **16/16 PASS**;
- усі 32 checks, які впали у наданому GitHub run — **32/32 PASS**;
- focused v1.12.x + v1.13.x suite — **68/68 PASS**.

Повний локальний `pytest -q` у sandbox не є authoritative, бо середовище не містить `aiogram` та `aiosqlite`. Обидва пакети є у project requirements; GitHub Actions встановлює `requirements-dev.txt` і має виконати повний gate з PostgreSQL 16.

## Production acceptance після push

1. GitHub Actions — зелений повний test gate.
2. Deploy job — зелений.
3. `web.1` і `worker.1` — `up`.
4. Alembic current — `20260915_0002 (head)`.
5. `/health/ready` — HTTP 200 / ready.
6. `/health/dependencies` — HTTP 200 після startup grace; worker + schedulers healthy.
7. Telegram `/start`, `/menu`, Події/Квести/Можливості — smoke PASS.
8. Web login/2FA, Event Cockpit, Analytics, Reports — smoke PASS.
9. Version-update notification — одна на користувача для v1.13.0.1.
