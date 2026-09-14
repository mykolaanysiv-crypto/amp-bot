# AMP XP / АМПасадори v1.7.4 — production update

## Що це за реліз

v1.7.4 — технічний реліз Reliability & Architecture на базі v1.7.3. Він не змінює основну логіку участі, але робить scheduler, Telegram-доставку, розсилки, тести та структуру web-коду значно надійнішими.

## Перед оновленням

1. Переконайтесь, що поточний production стабільний і `/health` відповідає.
2. Створіть Heroku PostgreSQL backup.
3. Збережіть локальний `.env` окремо.
4. Не запускайте `migrate_sqlite_to_postgres.py` — v1.7.4 використовує стандартну additive release-міграцію.
5. Не видаляйте чинні security Config Vars v1.7.3 (`WEB_SESSION_SECRET`, `SUPERADMIN_IDS` тощо).

## Зміни БД

- v1.7.3: 42 таблиці.
- v1.7.4: 44 таблиці.
- Нові: `scheduled_jobs`, `notification_deliveries`.
- `broadcast_recipients` отримує retry-поля: `attempt_count`, `last_attempt_at`, `next_retry_at`.
- Міграція ідемпотентна: повторний запуск release init не дублює структуру.

## Після deploy

Перевірте:

- `/health` → версія `1.7.4`;
- `heroku ps` → `web.1 up`;
- `/admin/system-health` → Database, Bot та Scheduler без критичних помилок;
- Telegram-бот відповідає;
- тестова подія/нагадування або системне повідомлення не дублюється;
- розсилки мають retry-статуси замість втрати одержувача після першої помилки.

## System Health

Новий web-розділ `🩺 Стан системи` показує:

- доступність PostgreSQL;
- доступність Telegram Bot API;
- стан scheduler/job locks;
- останню успішну job та останню помилку;
- pending/retry/failed Telegram deliveries;
- failed broadcasts та одержувачів у retry;
- APP_VERSION, Heroku release/commit/dyno — якщо Heroku передав ці env metadata;
- кількість/розмір media assets;
- локальний/внутрішній backup marker, якщо він є.

> Heroku PG Backups є зовнішнім сервісом Heroku, тому застосунок не може гарантовано читати його список без окремого Heroku API credential. Production backup перед deploy усе одно перевіряйте через `heroku pg:backups`.

## Retry policy

Durable Telegram outbox:

`pending → перша спроба → retry 1 (через 1 хв) → retry 2 (через 5 хв) → retry 3 (через 15 хв) → failed`, якщо всі 4 спроби невдалі

Broadcast recipients використовують аналогічний підхід. Це захищає від коротких мережевих/Telegram-помилок.

## Scheduler lock

Кожна критична job бере DB lease у `scheduled_jobs`. Якщо запущено два процеси, другий не виконує той самий job, поки lease активний. Після завершення записується success/error state.

## Rollback

Якщо production не стартує:

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku rollback vXX -a amp-bot-ver-1-5-0
```

Де `vXX` — останній стабільний release.

Нові таблиці/колонки additive, тому rollback коду не вимагає видаляти їх з БД.
