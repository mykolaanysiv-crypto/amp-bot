# AMP XP / «АМПасадори» v1.8.1 — 👤 Participant 360 & Lifecycle

## Що змінюється

v1.8.1 є additive-релізом поверх v1.8.0. Security-рівень v1.7.3, distributed reliability/idempotency v1.7.4, функції подій/referrals/donor forms v1.7.4.1 та Admin UX v1.8.0 збережені.

### 1. Життєвий цикл учасника

Додано два **автоматичні** статуси:

- `deleted` → **Видалено**;
- `deleted_permanent` → **Видалено без можливості відновлення**.

Ці статуси **не можна встановити вручну** у web. При переході в них запис учасника не видаляється: профіль, XP, відвідування, волонтерські години, документи, audit та звітні зв’язки залишаються в PostgreSQL.

Політика неактивності:

- 55 днів без Telegram-взаємодії → попередження за 5 днів;
- 59 днів → фінальне попередження за 1 день;
- 60 днів → автоматичний `deleted` і закриття доступу до функцій бота;
- blocked профілі та staff-ролі не обробляються цим правилом.

Якщо Telegram повертає `Forbidden` для активного participant/ambassador, профіль також переходить у `deleted`; чинний 30-денний referral clawback продовжує працювати idempotently.

### 2. Відновлення

`/start` для `deleted` показує кнопку `♻️ Так, відновити акаунт`.

Коротка форма питає:

1. чому учасник хоче повернутися;
2. у яких активностях планує брати участь;
3. підтвердження умов 14-денного випробувального строку.

Запит потрапляє до superadmin у web. Лише superadmin може **схвалити або відхилити** restoration request.

Після схвалення:

- status → `active`;
- починається 14-денний probation;
- підтверджена участь у події / квесті / волонтерській задачі / активності / опитуванні (або інша зафіксована участь у workflow) автоматично завершує probation успішно;
- якщо на момент завершення 14 днів участі немає → автоматичний `deleted_permanent`;
- `deleted_permanent` не має restoration workflow.

### 3. Participant 360

Картка `/admin/users/{id}` тепер містить:

- ім’я, AMP-ID, status/role;
- lifetime XP, сезонну лігу, streak, волонтерські години;
- KPI: події, квести, задачі, активності, опитування, ідеї, бейджі, referrals;
- єдиний timeline XP/подій/квестів/задач/активностей/ідей/опитувань/бейджів;
- вкладки `Огляд | Активність | XP | Події | Волонтерство | Ідеї | Опитування | Бейджі | Документи`;
- restoration request / probation state у тій самій картці.

### 4. Автоматичні повідомлення про новий контент

Всім профілям зі статусом `active` автоматично ставиться повідомлення в надійну Telegram delivery-систему, коли стає доступним новий:

- event;
- quest;
- volunteer task;
- activity;
- survey;
- opportunity.

Для web-створення використовується persistent broadcast campaign/retry. Telegram-admin creation використовує durable notification outbox. Тимчасові помилки Telegram не гублять повідомлення.

### 5. Аналітика та звіти

Додано/розширено:

- lifecycle distribution профілів;
- participation mix по ключових механіках;
- deleted / deleted_permanent;
- pending restoration requests;
- active probation;
- підтверджені дії участі;
- active/inactive профілі у звітах;
- середній XP на залученого учасника.

`Health` у web UI називається **🩺 Стан системи**.

## База даних

Нових таблиць немає: **44 таблиці**.

До `users` additive/idempotent migration додає nullable поля lifecycle/restoration:

- `deleted_at`;
- `deletion_reason`;
- `restoration_requested_at`;
- `restoration_request_status`;
- `restoration_answers_json`;
- `restoration_reviewed_at`;
- `restoration_reviewed_by`;
- `restored_at`;
- `probation_started_at`;
- `probation_until`;
- `permanent_deleted_at`.

Повторний SQLite → PostgreSQL перенос **не потрібний**.

## Перед deploy

```bash
cd ~/Downloads/amp_bot_v155
heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
```

Після копіювання v1.8.1:

```bash
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m compileall -q app scripts tests
pytest -q
git diff --check
```

## Deploy

```bash
git add -A
git commit -m "AMP XP v1.8.1 Participant 360"
git push heroku main
```

Heroku release-команда лишається:

```text
python -m scripts.heroku_release
```

Не запускайте вручну SQLite→PostgreSQL migration.

## Після deploy

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku ps -a amp-bot-ver-1-5-0
curl -s https://amp-bot-ver-1-5-0-9632a1434a6d.herokuapp.com/health
heroku logs -n 200 -a amp-bot-ver-1-5-0
```

Очікувана версія `/health`: `1.8.1`.

Перевірити вручну:

1. Participant 360 для активного учасника.
2. `deleted` профіль не має доступу до меню, але `/start` показує restoration.
3. restoration form → pending request → approve superadmin → probation.
4. `deleted` / `deleted_permanent` немає серед ручних status options.
5. Створення відкритої події/квесту/задачі/активності/опитування/можливості створює автоматичне повідомлення active-аудиторії.
6. `🩺 Стан системи` та scheduler job працюють без error.
