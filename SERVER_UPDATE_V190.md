# AMP XP / «АМПасадори» v1.9.0 — Notification Center & Outcomes

## Що змінено

### 🔔 Єдиний Notification Center

Усі proactive Telegram-повідомлення тепер використовують канонічну таблицю `notifications` і один delivery/retry worker.

Новий запис містить:
- одержувача (`recipient_user_id` + Telegram ID);
- `type`;
- `title`;
- `body`;
- `entity_type` / `entity_id`;
- `scheduled_at` / `sent_at`;
- `status`;
- `error`;
- `retry_count`;
- idempotent `dedupe_key`.

Legacy `notification_deliveries` не видаляється з production-схеми, щоб не ламати старі дані. Під час `release/startup` її рядки ідемпотентно переносяться в `notifications`, після чого нові producers працюють тільки через новий механізм.

### Web → 🔔 Сповіщення

Додано `/admin/notifications`:
- KPI `В черзі`;
- `Надіслано`;
- `Помилки`;
- фільтр типу;
- фільтр статусу;
- пошук по title/body;
- `🔁 Повторити невдалі`.

Типи для фільтрації:
- системні;
- події;
- розсилки;
- кейси;
- streak;
- опитування.

### ⭐ Feedback після події

Приблизно через 2 години після підтвердженої присутності активний учасник отримує:
1. оцінку 1–5;
2. `Було корисно?`;
3. `Дізнався/дізналася щось нове?`;
4. `Почувався/почувалася безпечно?`;
5. `Хочеш прийти ще?`;
6. необов'язковий коментар.

Feedback не запускається заднім числом для всіх старих подій: перший startup v1.9.0 ставить marker початку функції.

### 📊 Outcomes

На сторінці події показуються:
- середня оцінка;
- % корисності;
- % нових знань;
- % безпеки;
- % учасників, які хочуть повернутися.

Ці показники також входять у:
- загальну аналітику;
- Excel;
- PDF;
- автоматичні періодичні звіти.

PDF містить окрему сторінку `Вплив` із donor/council-friendly формулюваннями.

## База даних

v1.9.0 додає 2 таблиці:
- `notifications`;
- `event_feedback`.

Поточна SQLAlchemy metadata: **46 таблиць**.

Міграція additive/idempotent. Повторно переносити SQLite → PostgreSQL НЕ потрібно.

## Deploy на Heroku

Перед deploy:

```bash
heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
```

Далі оновіть робочу папку кодом v1.9.0, перевірте:

```bash
cat VERSION.txt
python -m compileall -q app scripts tests
pytest -q tests/test_v181_features.py tests/test_v182_ui.py tests/test_v1821_calendar_event_ops.py tests/test_v1822_startup_hotfix.py tests/test_v1823_runtime_fixes.py tests/test_v1824_telegram_scanner.py tests/test_v1825_admin_menu_version_dedupe.py tests/test_v190_notification_center.py
```

Потім:

```bash
git add -A
git commit -m "AMP XP v1.9.0 Notification Center and Outcomes"
git push heroku main
```

Перевірка production:

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku ps -a amp-bot-ver-1-5-0
curl -s https://amp-bot-ver-1-5-0-9632a1434a6d.herokuapp.com/health
heroku logs -n 250 -a amp-bot-ver-1-5-0
```

`/health` має показувати `1.9.0`.

## Після deploy перевірити вручну

1. Web → `🔔 Сповіщення` відкривається без помилок.
2. Створити тестове proactive notification або broadcast і перевірити status `queued → sent`.
3. Перевірити `🔁 Повторити невдалі` на test failed row, якщо є.
4. Відкрити завершену подію та перевірити блок `⭐ Feedback та вплив`.
5. Для нової тестової події з підтвердженою attendance перевірити feedback після scheduler window.
6. Сформувати Excel/PDF звіт і перевірити блок/сторінку `Вплив`.

## Важливо

- 2FA код web-login навмисно залишається immediate direct Telegram send, а не durable queue: це короткоживучий security token.
- Звичайні Telegram-відповіді бота під час активного діалогу/FSM (`message.answer`) не є proactive notifications і не записуються у Notification Center.
- Усі фонові/системні participant-facing Telegram notifications проходять через `notifications`.
