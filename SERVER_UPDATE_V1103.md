# АМП XP / «АМПасадори» v1.10.3 — Data Integrity & Data Quality

## 1. Мета релізу

v1.10.3 — P0-реліз без розширення продуктового меню. Він закриває ризики передчасного attendance/XP, очищує звітні KPI від майбутніх подій та вводить canonical-довідник населених пунктів.

## 2. Check-in / attendance window

Нові runtime settings:

- `events.checkin_open_before_minutes = 60` — QR/check-in відкривається за 60 хв до старту;
- `events.checkin_close_after_minutes = 360` — звичайний check-in/attendance закривається через 360 хв після старту.

Налаштування можна змінювати у web Runtime Settings без deploy. Межі вікна включні: рівно у момент відкриття та рівно у момент закриття check-in дозволений.

`Event.starts_at` у поточній схемі є локальним wall-clock datetime, тому v1.10.3 використовує `TIMEZONE` (за замовчуванням `Europe/Kyiv`) для event-clock. Це прибирає зсув check-in window на Heroku/UTC.

Захищені канали:

- QR події у Telegram;
- персональний QR через Telegram scanner;
- Telegram admin bulk-confirm;
- browser QR scanner;
- ручний `mark-present`;
- підтвердження одного checked-in учасника;
- bulk attendance confirmation.

Поза вікном звичайний attendance/XP заблокований.

## 3. Manual override

Виняток доступний у web-панелі для працівника з доступом до редагування подій.

Поза window web вимагає причину мінімум 5 символів. У audit записується дія `web_event_attendance_override` із:

- event id;
- типом override (mark-present / confirm / bulk confirm);
- станом window (`too_early` / `closed`);
- причиною;
- кількістю підтверджених учасників для bulk.

Telegram bulk-confirm навмисно не робить silent override: бот перенаправляє працівника до web-панелі.

## 4. Idempotency attendance / XP

`confirm_single_event_attendance()`:

- працює лише зі статусом `checked_in`;
- повторне підтвердження `attended` повертає `None`;
- registration перечитується під `FOR UPDATE` з `populate_existing=True` перед XP;
- XP/години/attendance signature створюються один раз.

## 5. Reporting integrity

У `build_period_report()` події розділено на:

- completed;
- upcoming;
- in progress.

Attendance KPI враховує лише `attended` з завершених подій. Legacy/помилковий `attended` на майбутній події:

- не збільшує `visits`;
- не збільшує `avg_attendance`;
- не збільшує `unique_participants`;
- у рядку майбутньої події показує `Відвідали = 0`;
- потрапляє у технічний KPI `future_attendance_anomalies`.

`events` тепер означає завершені події. Додано:

- `events_planned`;
- `events_upcoming`;
- `events_in_progress`.

`unique_participants` означає реально залучених через attendance / approved quest / approved volunteering / completed activity / idea / request / survey response. Сам факт створення профілю більше не робить людину «унікальним учасником».

У Excel/PDF KPI розділено на:

- **ЗА ПЕРІОД**;
- **СТАНОМ НА ДАТУ ФОРМУВАННЯ**.

Snapshot включає lifecycle-профілі та дані про відновлення; period metrics — події, участь, XP, feedback тощо.

## 6. Data Quality / населені пункти

Додано таблицю `settlement_references` (schema = 48 tables).

Canonical normalization:

- `Анисів` → `Анисів`;
- `Анисiв` → `Анисів`;
- `с.Анисів` → `Анисів`;
- `с. Анисів` → `Анисів`;
- `село Анисів` → `Анисів`.

Так само seed-словник містить безпечні aliases для Іванівки, Бакланової Муравійки, Василькова та Лукашівки. Інші реальні населені пункти не видаляються: вони можуть стати власними canonical entries.

Під час startup `bootstrap_defaults()` idempotently:

1. створює/оновлює directory;
2. приводить наявні профілі до відомих canonical values;
3. зберігає невідомі легітимні назви;
4. не змінює дані повторно після нормалізації.

Нові/відредаговані профілі проходять `resolve_canonical_settlement()`.

Canonical matching використовується в:

- registration/profile edits;
- analytics;
- broadcast audience `settlement`;
- Smart Opportunities;
- period reports.

## 7. Data Quality widget

Dashboard отримав блок **🧹 Якість даних**:

- кількість canonical values;
- профілі з населеним пунктом;
- duplicate groups;
- noncanonical values;
- стан ✅ / ⚠️;
- кнопку «Перевірити й нормалізувати» для `participants.edit`.

Кнопка журналюється як `web_settlement_data_quality_normalize`.

Окрім exact aliases, widget консервативно сигналізує про дуже схожі canonical назви як можливі typo-дублікати. Він не зливає їх автоматично.

## 8. Схема БД

v1.10.3: **48 SQLAlchemy tables**.

Нова additive таблиця:

`settlement_references`

`Base.metadata.create_all()` створює її idempotently на існуючій БД. Дані користувачів не переносяться в іншу таблицю; `users.settlement` залишається сумісним текстовим полем, але значення нормалізуються через directory.

## 9. QA

Новий behavioral suite: `tests/test_v1103_data_integrity.py`.

Перевіряє:

- check-in за день до події;
- check-in за 61 хв до події;
- inclusive open/close boundaries;
- check-in після window;
- manual override із/без причини;
- repeat check-in;
- double attendance / double XP;
- future event у monthly report;
- settlement alias normalization;
- наявність web override reason + audit path.

Під час release QA:

- `python -m compileall -q app scripts tests` — PASS;
- Jinja parse: 48 templates, 0 errors;
- SQLAlchemy metadata: 48 tables;
- pytest: 100/100 PASS у ізольованому QA-середовищі. Через відсутність встановлених `aiosqlite`/`aiogram` у sandbox використовувалися лише тимчасові test-only compatibility shims; вони не включені у релізний ZIP і production dependencies залишаються з `requirements.txt`.
- report smoke: Excel/PDF генеруються; future attendance виключається з KPI.

## 10. Після deploy

1. Переконатися, що `/health` показує `APP_VERSION=1.10.3`.
2. Відкрити **Runtime Settings → Події** та перевірити 60/360 хв.
3. Відкрити **Dashboard → Якість даних**.
4. Перевірити, що `Анисiв` / `с.Анисів` стали `Анисів`.
5. Створити тестову подію >60 хв у майбутньому і перевірити, що QR повертає «ще не відкрито».
6. Перевірити подію в дозволеному window: check-in → confirm → XP один раз.
7. Спробувати ручний override поза window та перевірити запис в Audit.
8. Згенерувати місячний PDF/XLSX і перевірити окремі period/snapshot KPI.
