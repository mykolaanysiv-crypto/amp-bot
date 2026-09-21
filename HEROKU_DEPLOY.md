
## v1.12.1.5 — verified backup gate

Production deploy через GitHub Actions тепер перед `git push` у Heroku:
1. створює `heroku pg:backups:capture`;
2. перевіряє список PGBackups;
3. записує `last_backup_at` через `scripts.mark_backup_verified`;
4. перевіряє marker через `scripts.verify_backup_marker`;
5. тільки після успіху деплоїть протестований commit.

Окремий workflow **AMP Verified Backup** запускається щодня і вручну з GitHub Actions. Для нього використовуються ті самі `HEROKU_API_KEY` та `HEROKU_APP_NAME`.

Опційно: `BACKUP_UNKNOWN_GRACE_HOURS=24`. Якщо marker ще ніколи не створювався, система не надсилає false-positive Telegram alarm протягом grace, але й не позначає backup як перевірений.

# Heroku deployment — АМПасадори v1.17.2.3

> **Production Stability Gate:** рекомендований production deploy тепер проходить через GitHub Actions. PostgreSQL 16 CI виконує compile, tests, integration tests і реальний release/startup smoke; deploy job стартує лише після PASS.

Process types:

```text
release: python -m scripts.heroku_release
web: python run_web.py
worker: python run.py
```

Release phase реально проходить `Alembic upgrade head → db.init() → bootstrap_defaults() → FastAPI lifespan`. Якщо startup падає, Heroku не промотує новий реліз.

## Перед deploy

1. Зробіть PostgreSQL backup.
2. Не змінюйте `DATABASE_URL` або `WEB_SESSION_SECRET` без окремої причини.
3. Переконайтеся, що секрети є у Heroku Config Vars, а не у Git.
4. Після накладання v1.12.0 бажано використовувати helper:

```bash
./scripts/heroku_capture_verified_backup.sh amp-bot-ver-1-5-0
```

## Deploy

Рекомендовано: push/merge у GitHub `main`. Workflow `.github/workflows/ci.yml` запускає job **Production gate**, а `deploy` має `needs: test`.

Для GitHub repository secrets задайте:

- `HEROKU_API_KEY`
- `HEROKU_APP_NAME=amp-bot-ver-1-5-0`

Прямий `git push heroku HEAD:main` залишайте тільки як emergency path: він технічно обходить GitHub CI, якщо доступ до Heroku Git не обмежено зовнішніми налаштуваннями.


Release phase виконує:

1. `alembic upgrade head` — єдиний production-шлях зміни схеми;
2. `db.init()` — лише перевірка підключення/runtime PRAGMA, без DDL;
3. `bootstrap_defaults()` після актуалізації schema;
4. реальний FastAPI/worker startup smoke;
5. production preflight.

## Scale

Після deploy окремо увімкніть worker:

```bash
heroku ps:scale web=1 worker=1 -a amp-bot-ver-1-5-0
```

Перевірка:

```bash
heroku ps -a amp-bot-ver-1-5-0
heroku logs --tail -a amp-bot-ver-1-5-0
```

Очікується, що `web.1` і `worker.1` мають статус `up`.

## Config Vars

Обов'язкові для production:

- `BOT_TOKEN`
- `DATABASE_URL`
- `SUPERADMIN_IDS`
- `WEB_SESSION_SECRET`
- `PUBLIC_BASE_URL`
- `MEDIA_STORAGE=database`
- `COOKIE_SECURE=1`
- `MONOBANK_TOKEN`
- `DONATION_JAR_URL`
- `TIMEZONE=Europe/Kyiv`

Рекомендовані:

```bash
heroku config:set APP_ENV=production LOG_LEVEL=INFO -a amp-bot-ver-1-5-0
```

Optional Sentry:

```bash
heroku config:set SENTRY_DSN="..." SENTRY_TRACES_SAMPLE_RATE=0.0 -a amp-bot-ver-1-5-0
```

## Backup verification

Після успішного Heroku PGBackup:

```bash
heroku run -a amp-bot-ver-1-5-0 -- python -m scripts.mark_backup_verified "Heroku PGBackup verified"
heroku run -a amp-bot-ver-1-5-0 -- python -m scripts.verify_backup_marker
```

System Health вважає verified backup актуальним протягом 168 годин. Worker rate-limit'ить warning суперадмінам до одного разу на 24 години.

## Rollback

У разі application regression використовуйте Heroku Releases rollback. Не очищайте production PostgreSQL. v1.17.2 використовує Alembic як єдине джерело схеми; runtime legacy upgrader видалено. Перед rollback не відкочуйте БД вручну без перевіреної процедури.
