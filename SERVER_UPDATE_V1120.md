# АМПасадори v1.12.0 — Codebase Refactor, Production Engineering & Gamification 2.0

v1.12.0 — технічний production-реліз поверх v1.11.1. Його принцип: **не змінювати зовнішню поведінку учасника/адміністратора без потреби**, але зробити код, деплой, спостережуваність і аналітику гейміфікації безпечнішими для подальшого росту.

## 1. Codebase Refactor

- `app/services.py` перетворено на backward-compatible facade; реалізація розкладена в `app/domain_services/`:
  - `users.py`
  - `events.py`
  - `gamification.py`
  - `referrals.py`
  - `teams.py`
  - `qr.py`
  - `exports.py`
  - `moderation.py`
  - `audit.py`
  - `bootstrap.py`
  - `common.py`
- Старі імпорти `from app.services import ...` залишаються робочими.
- Великі Telegram handlers розділено на доменні модулі; `admin.py` і `participant.py` тепер є compatibility facade.
- `admin` розкладено на core / events / quests+rewards / activities+tasks / opportunities / moderation.
- `participant` розкладено на home / requests / opportunities / activities / tasks.

## 2. Alembic — поступова міграція

- Додано `alembic.ini`, `migrations/env.py` та baseline revision `20260915_0001_v1111_baseline.py`.
- v1.12.0 не змінює production schema відносно v1.11.1: **53 таблиці**.
- Для старих інсталяцій release phase спочатку виконує перевірений idempotent legacy compatibility bootstrap, а потім `alembic upgrade head`.
- Baseline свідомо no-op: він переводить production БД під контроль Alembic без небезпечного повторного створення історичних колонок.
- Нові schema changes після baseline мають оформлюватися Alembic revisions, а не додаватися до legacy upgrader.

## 3. Production Engineering

### Web / worker separation

`Procfile`:

```text
release: python -m scripts.heroku_release
web: python run_web.py
worker: python run.py
```

- web-process обслуговує FastAPI/web-панель;
- worker-process обслуговує Telegram polling, Notification Center, нагадування, streaks, lifecycle, Smart Opportunities, Monobank sync і production health alerts;
- падіння Telegram polling не повинно завершувати web dyno;
- deadline lifecycle scheduler перенесено у worker, при цьому relevant web pages зберігають request-time refresh як fallback.

### CI

`.github/workflows/ci.yml` запускається на кожний `push`, `pull_request` та вручну:

- Python compile;
- production preflight;
- unit/regression tests;
- PostgreSQL 16 integration tests;
- Alembic/release smoke;
- migration head verification.

На кожному Heroku deploy release phase окремо виконує production bootstrap + Alembic + preflight.

### Structured monitoring

- JSON logs на Heroku (`service`, `level`, `logger`, `message`, `request_id`, `dyno`, exception metadata);
- redaction для BOT_TOKEN, MONOBANK_TOKEN, DATABASE_URL, WEB_SESSION_SECRET, SENTRY_DSN, HEROKU_API_KEY;
- `X-Request-ID` correlation id для web-запитів;
- optional Sentry через `SENTRY_DSN`, `send_default_pii=False`;
- cookies/auth headers/X-Token та user PII прибираються перед відправленням event у Sentry.

### Notification Center alerts

- worker раз на 5 хв перевіряє нові `failed` Notification Center deliveries;
- direct alert суперадмінам навмисно обходить проблемну outbox-чергу;
- alert не містить body повідомлень чи контактів, лише aggregate counts/types/ID range.

### Backup verification

- `scripts/heroku_capture_verified_backup.sh` створює Heroku PGBackup і тільки після успішної capture-команди записує verification marker в АМП;
- System Health показує час/вік останньої підтвердженої копії;
- worker раз на 6 год перевіряє marker і не частіше одного разу на добу попереджає суперадмінів, якщо verified backup відсутній або старший за 168 год.

## 4. Gamification 2.0

Новий web-екран **🧠 Гейміфікація 2.0** доступний для `analytics.view` або `gamification.manage`.

Він аналізує:

- фактичний поточний розподіл Bronze / Silver / Gold / Platinum / Diamond / Legendary;
- переходи між лігами й медіану часу до переходу;
- repeat participation, 7-day та 28-day retention;
- XP по категоріях, середній XP/дію, частку категорій у загальному XP;
- reward claims, fulfillment rate та `XP spent / XP earned`;
- Smart Opportunities: matches → notified → interested;
- referral: invite → first real activity → rewarded.

### Clean-data guardrail

- при першому відкритті v1.12 фіксується `gamification.clean_data_start`;
- effectiveness/retention/referral/opportunity metrics використовують тільки записи після цієї baseline;
- історичний XP використовується лише для коректної стартової ліги, але старі переходи не рахуються як v1.12 transitions;
- до 28 днів система прямо рекомендує **не змінювати XP**;
- 28–55 днів — лише preliminary review;
- після 56 днів можна готувати ручне рішення;
- **система ніколи не змінює XP, league thresholds або rewards автоматично**.

## 5. Production Config Vars

Обов'язкові/існуючі:

- `BOT_TOKEN`
- `DATABASE_URL`
- `WEB_SESSION_SECRET`
- `MONOBANK_TOKEN`
- `DONATION_JAR_URL`
- `SUPERADMIN_IDS`
- `TIMEZONE=Europe/Kyiv`

Рекомендовані:

```text
APP_ENV=production
LOG_LEVEL=INFO
SENTRY_DSN=...        # optional
SENTRY_TRACES_SAMPLE_RATE=0.0
```

## 6. Після deploy

1. Переконатися, що `web.1` і `worker.1` мають статус `up`.
2. `/health` має показувати `1.12.0`.
3. Відкрити `🩺 Стан системи`: DB, Telegram, scheduler, Notification Center, backup marker.
4. Відкрити `🧠 Гейміфікація 2.0`: на першому запуску має бути 0 днів clean baseline.
5. Переконатися, що старі функції Telegram/Web поводяться як у v1.11.1.
