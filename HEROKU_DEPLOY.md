# Heroku deployment — АМПасадори v1.12.0

v1.12.0 використовує окремі process types:

```text
release: python -m scripts.heroku_release
web: python run_web.py
worker: python run.py
```

## Перед deploy

1. Зробіть PostgreSQL backup.
2. Не змінюйте `DATABASE_URL` або `WEB_SESSION_SECRET` без окремої причини.
3. Переконайтеся, що секрети є у Heroku Config Vars, а не у Git.
4. Після накладання v1.12.0 бажано використовувати helper:

```bash
./scripts/heroku_capture_verified_backup.sh amp-bot-ver-1-5-0
```

## Deploy

```bash
git add -A
git commit -m "Upgrade AMP to v1.12.0 production engineering"
git push heroku HEAD:main
```

Release phase виконує:

1. legacy compatibility bootstrap для старих production DB;
2. `alembic upgrade head`;
3. production preflight.

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

У разі application regression використовуйте Heroku Releases rollback. Не очищайте production PostgreSQL. Alembic baseline v1.12.0 є no-op; schema залишається сумісною з v1.11.1.
