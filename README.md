# AMP XP / «АМПасадори» v1.13.0.4 — CI Localization & Test Time Hotfix

v1.13.0.4 — мінімальний CI hotfix поверх v1.13.0.3. Виправлено historical regression assertion, який після української локалізації Notification Center усе ще очікував англійське `Streak`, а також прибрано `datetime.utcnow()` з Smart Opportunities regression test для Python 3.13. Production-код, схема БД та користувацький UX не змінюються.

## Що виправлено у v1.13.0.4

- `tests/test_v190_notification_center.py` тепер перевіряє канонічну українську назву `Серії участі`.
- `tests/test_v11303_telegram_web_ux_hotfix.py` більше не pin-ить точний patch `1.13.0.3`, а валідно працює для наступних `1.13.0.x` hotfix-релізів.
- `tests/test_v192_smart_opportunities_seasons.py` використовує project `Clock`: `clock.storage_utc()` та `clock.today_local()` замість deprecated `datetime.utcnow()` / прямого `date.today()` у відповідному тесті.
- Версію і cache-busting tokens синхронізовано до `1.13.0.4`.
- Нової Alembic migration немає; head залишається `20260915_0002`.

---

## Історія: AMP XP / «АМПасадори» v1.13.0.3 — Telegram Navigation & Web Localization Hotfix

v1.13.0.3 — user-facing patch поверх v1.13.0.2. Виправлено `/start`/`/menu` для активних користувачів після Architecture Completion, додано повноцінну `/smart`, відновлено примусове оновлення актуальної reply-клавіатури, прибрано програмне обрізання назв винагород і локалізовано відомі англомовні labels у web-панелі.

## Що виправлено у v1.13.0.3

- active `/start` і `/menu` більше не падають на lazy import `participant`; `/menu` знову показує «Головна» та встановлює актуальну reply-клавіатуру;
- `/smart` додано в BotCommand menu, handler, FSM navigation і `/help`; перед показом можливостей matching оновлюється;
- `rewards_keyboard()` більше не використовує 28-символьне обрізання — назва винагороди лишається повною;
- web labels `Participant 360`, `Referrals`, `Timeline`, `SEASONS & HISTORY`, `Freeze`, `SLA`, `manual override/check-in window` локалізовано;
- Notification Center показує локалізовані відомі internal type/entity/status замість raw codes;
- preflight і regression tests блокують повернення цих помилок;
- schema без змін: 54 таблиці, Alembic head `20260915_0002`.

Деталі: `SERVER_UPDATE_V11303.md`. Команди: `COMMANDS_V11303.txt`. QA: `TEST_REPORT_V11303.txt`.

---

# AMP XP / «АМПасадори» v1.13.0.2 — Startup Import Hotfix

v1.13.0.2 — patch-реліз поверх v1.13.0.1. Виправлено release/startup crash після Architecture Completion: модулі `app.handlers.start_flow` використовували неправильну глибину relative imports і намагалися імпортувати неіснуючі `app.handlers.time_utils`, `app.handlers.config` тощо. Додано generic preflight guard для всіх explicit relative module imports у `app/` та синхронізовано static asset cache-buster з поточною версією.

## Що виправлено у v1.13.0.2

- `start_flow/common.py`: root-app imports переведено з `..module` на `...module`;
- `start_flow/entry.py`: `gamification` також імпортується з кореня `app`;
- `production_preflight`: unresolved relative imports тепер блокують release до GitHub/Heroku startup;
- `base.html`, `login.html`, `login_2fa.html`: cache token оновлено до v1.13.0.2;
- schema не змінюється, Alembic head залишається `20260915_0002`.

---

# AMP XP / «АМПасадори» v1.13.0.1 — Architecture CI Compatibility Hotfix

v1.13.0.1 — малий patch-реліз поверх Architecture Completion. Він не повертає старі моноліти і не змінює бізнес-логіку: оновлено regression suite, щоб historical safety/UX checks читали canonical source modules після split-архітектури v1.13.0.

## Що виправлено у v1.13.0.1
- Додано централізований `tests/source_layout.py` для source-inspection regression tests.
- 32 CI failures після v1.13.0 переведені зі старих facade paths на canonical implementations.
- Scanner regression перевіряє `app/web/event_routes/operations.py`; body-param guard охоплює обидва route packages.
- Web 2FA direct Telegram path allowlisted у `app/web/auth_routes.py`; Notification Center invariant для business notices збережений.
- Version announcement tests переведені на `app/web/broadcast_runtime.py` і `app/web/lifespan.py`.
- PostgreSQL schema без змін: **54 таблиці**, Alembic head — `20260915_0002`.

## Базова архітектура v1.13.0
- `app/web/app.py` перетворено на малий compatibility facade; canonical FastAPI composition тепер у `app/web/factory.py` через `create_app()`.
- `run_web.py` запускає Uvicorn напряму в factory mode: `app.web.factory:create_app`.
- Shared web dependencies/helpers винесені в `app/web/dependencies.py`; health, auth, media, lifespan і broadcast runtime — у окремі модулі.
- Великий `app/web/routes/events.py` розділено на `app/web/event_routes/`: overview, participants, operations, mutations, scanners і public routes. Старий import path тимчасово збережений facade-модулем.
- `app/analytics.py` розділено на `app/analytics_modules/core.py` та `exports.py`; `app/reports.py` — на `app/reporting/periods.py`, `builder.py`, `exports.py`.
- SQLAlchemy models розділено за доменами у `app/model_domains/`; `app/models.py` лишився явним compatibility facade. Metadata повністю збережена: **54 таблиці**.
- `/start` / registration flow розділено на `app/handlers/start_flow/`; `app/handlers/start.py` лишився facade.
- Telegram middleware та dispatcher composition винесені з `app/main.py` у `app/telegram_middleware.py` і `app/bot_runtime.py`.
- Усі 13 scheduler перенесені в `app/jobs/` з єдиним `scheduler_factories()` registry; `app/main.py` тепер лише orchestration entry point.
- Прибрано **всі `import *` у `app/`**; compatibility modules використовують тільки explicit imports/exports.
- Production preflight отримав Architecture Completion gates: factory mode, наявність split packages, facade-size limits, заборона wildcard imports та continuity Alembic/schema.
- Startup smoke тепер тестує canonical `create_app()` і окремо перевіряє import compatibility facade.
- Compatibility facades залишаються на **1–2 релізи** для безпечного переходу; після міграції внутрішніх/зовнішніх import paths вони мають бути видалені окремим cleanup-релізом.

## Сумісність
- PostgreSQL schema: **без змін**, 54 таблиці.
- Alembic head: `20260915_0002`.
- XP, Notification Center, Content Views, Clock/time hardening, security/ACL, backup та worker/scheduler supervision не змінюють контракт.
- `app.models`, `app.analytics`, `app.reports`, `app.web.app`, `app.web.routes.events`, `app.handlers.start` залишаються доступними на перехідний період.

Деталі: `SERVER_UPDATE_V1130.md`. Команди: `COMMANDS_V1130.txt`. QA: `TEST_REPORT_V1130.txt`.

---

# AMP XP / «АМПасадори» v1.12.2 — Error & Time Hardening

v1.12.2 — reliability/hardening реліз поверх v1.12.1.7. Основний фокус: один часовий boundary через `Clock`, timezone-aware UTC для бізнес-рішень, DST-safe local-calendar періоди та machine-searchable error logs без silent broad exceptions.

## Що нового у v1.12.2
- Додано canonical `Clock` у `app/time_utils.py`: aware UTC, Europe/Kyiv local time, legacy DB adapters, local-period → UTC boundaries і DST-safe scheduler waits.
- Прямі `datetime.utcnow`, `datetime.now` і `date.today` прибрано з application/scripts коду поза `Clock`; SQLAlchemy defaults також проходять через `clock.storage_utc`.
- Production-БД не переписується: legacy `timestamp without time zone` лишається сумісним через явний persistence boundary; `Event.starts_at` лишається local-wall полем і конвертується в aware UTC для бізнес-рішень.
- Прибрано silent `except Exception: pass`; production preflight та regression test блокують їх повернення.
- Structured JSON logs підтримують стабільні `error_code` + `context`, bounded JSON-safe context і redaction token/secret/password-полів.
- Critical heartbeat/scheduler/broadcast/runtime/version/notification/backup error paths отримали machine-searchable error codes.
- Check-in window працює на aware UTC; scheduler waits коректно проходять spring/fall DST; report calendar boundaries конвертуються з Europe/Kyiv у UTC один раз на boundary.
- Reports, registration-day counters і season backfill більше не змішують local midnight з naive UTC storage.
- Нові tests покривають winter/summer offsets, autumn fold, spring DST scheduler wait, local midnight/month boundaries, check-in window і structured logs.
- Схема БД не змінюється від v1.12.1.7: **54 таблиці**, Alembic head — `20260915_0002`.

Деталі: `SERVER_UPDATE_V1122.md`. Команди: `COMMANDS_V1122.txt`. QA: `TEST_REPORT_V1122.txt`.

---

## Попередній реліз: v1.12.1.7 — Event Open + Content Views + Cockpit UX

- Картка події не блокується помилкою lifecycle-refresh; HTML екранується, довгі photo captions безпечно розділяються.
- Перегляди рахуються для подій, квестів, волонтерських задач, можливостей, активностей і опитувань.
- Web показує загальні перегляди; detail-екрани ключових сутностей — також унікальних глядачів.
- Event Operations Cockpit отримав уніфіковані відступи, вирівняні панелі/кнопки та адаптивний layout.

v1.12.1.1 — hotfix поверх v1.12.1. Production Stability Gate збережено; додатково виправлено regression каталогу стандартних винагород після refactor. Головний фокус: реальний release/startup smoke на PostgreSQL 16, CI gate перед рекомендованим deploy, health/readiness, heartbeat worker/schedulers і явні PostgreSQL pool limits.

## v1.12.1.6 — Health JSON Serialization Hotfix
- `/health/dependencies` безпечно серіалізує native `datetime` через FastAPI `jsonable_encoder` і більше не падає з HTTP 500 через heartbeat timestamps.
- Збережено Backup Verification Automation з v1.12.1.5: pre-deploy/щоденний Heroku PGBackup, marker verification і 24-годинний grace для першого `unknown` стану.

## Що нового у v1.12.1

- Release phase реально виконує `db.init() → bootstrap_defaults() → Alembic upgrade head → FastAPI lifespan` і імпортує worker до promotion релізу.
- GitHub Actions використовує PostgreSQL 16 і запускає regression/integration/release smoke; production deploy job має `needs: test`.
- Додано `/health/live`, `/health/ready`, `/health/dependencies` з HTTP 503 для неготового/degraded стану.
- Додано `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` і telemetry pool у dependency health.
- Worker та кожний scheduler пишуть heartbeat; web monitor виявляє dead/stale background process.
- Scheduler supervisor фіксує failure, надсилає alarm суперадміну і автоматично перезапускає задачу.
- Schema залишається 53 таблиці; heartbeat використовує існуючу `system_settings`.

Деталі: `SERVER_UPDATE_V1121.md`. Команди: `COMMANDS_V1121.txt`.

---

# AMP XP / «АМПасадори» v1.11.1 — 🎛 Event Operations & Reporting 2.0

v1.11.1 — операційний і звітний реліз поверх v1.11.0. Основний фокус: керування всією участю в події з одного екрану та звітність, у якій чітко розділено потік за період і стан бази на конкретну дату.

## Що нового у v1.11.1

- **Event Operations Cockpit** на сторінці події об’єднує `зареєстровані → черга/резерв → відмітка → підтверджено → XP → зворотний зв’язок`.
- У тому самому блоці видно **стан QR-сканера**, check-in window, останню дію сканера та оператора.
- Масові дії: оновити чергу/резерви для конкретної події, підтвердити всіх відмічених, після закриття вікна — позначити тих, хто не прийшов.
- Таблиця учасників показує статус, час відмітки, XP, зворотний зв’язок і код підтвердження без переходів у додаткові розділи.
- **Reporting 2.0** додає `Дані станом на … Europe/Kyiv`, окремі потокові й моментні KPI, дві conversion funnel, Data Quality та визначення показників.
- Додано звіт за **ISO-тиждень** і адаптивну динаміку: короткий період — по днях, середній — по тижнях, довгий — по місяцях.
- Якщо у вибірці лише одна точка, лінійний графік не малюється — показуються KPI.
- Майбутні події не можуть потрапити у фактичні attendance KPI через помилковий legacy status.
- У **Журналі доступу** виправлено колонку **«Хто»**: слова/імена більше не розбиваються всередині.
- Схема БД залишається **53 таблиці**.

Деталі оновлення: `SERVER_UPDATE_V1111.md`. Команди: `COMMANDS_V1111.txt`. QA: `TEST_REPORT_V1111.txt`.

---

## Архів релізу v1.11.0

# AMP XP / «АМПасадори» v1.11.0 — 🚀 UX & Conversion

v1.11.0 — продуктовий реліз поверх v1.10.4.1. Основний фокус: простіша реєстрація, короткий зворотний зв’язок, контекстна головна сторінка Telegram, операційний web-dashboard і посилений захист чутливих даних.

## Що нового у v1.11.0

- **Registration UX**: прогрес кроків, безпечне відновлення незавершеної реєстрації, кнопкові відповіді, autocomplete населеного пункту та зрозумілі validation-помилки.
- Чернетка незавершеної реєстрації зберігається **зашифрованою**, а воронка фіксує лише службові timestamps: `start → consent → profile → submit → approved → first activity`.
- **Feedback 2.0**: короткий micro-feedback в одному повідомленні, одноразове нагадування, conversion по кожній події та загальний response rate.
- **Next Best Action** у Telegram Home автоматично піднімає одну найважливішу дію: продовжити реєстрацію, feedback, подія сьогодні, нова відповідь у зверненні, майже виконана ціль або найближча подія. Старий блок `⚡ Швидкі дії` прибрано.
- Головне Telegram-меню має фіксований порядок: `🏠 Головна / 👤 Мій профіль`, `🚀 Долучитися / 🌍 Можливості`, `🎫 QR-бейдж / 🤝 Запросити друга`, `💙 Підтримати / 🆘 Звернення`, окремий ряд `☰ Ще`; `🛠 Адмін-панель` — окремий нижній ряд лише для ролей/користувачів із правами.
- **Operations Dashboard** у web: `Сьогодні`, `Потребує уваги`, SLA звернень, failed notifications, pending registrations, upcoming check-ins, no-show, feedback rate, registration funnel і data-quality issues.
- Для звернень додано точне відстеження **непрочитаних відповідей команди** через `participant_last_viewed_at`, щоб Home не показував застарілий сигнал.
- **Monobank / sensitive data hardening**: секрети не потрапляють у repr конфігурації, provider response body не виводиться в помилки, внутрішній jar account id не зберігається, `/admin` має `no-store`, донорські чутливі поля маскуються для всіх, крім суперадміністратора.
- Збережено hotfix v1.10.4.1 для `sendId` Monobank у форматах `jar/<id>`, `<id>` та повного URL.
- Схема БД: **53 таблиці**; міграції additive/idempotent.
- Нова залежність: `cryptography>=43,<47` для шифрування checkpoint-чернеток реєстрації.

Деталі оновлення: `SERVER_UPDATE_V1110.md`. Команди: `COMMANDS_V1110.txt`. QA: `TEST_REPORT_V1110.txt`.

---

## Архів релізу v1.10.4 / v1.10.4.1

# AMP XP / «АМПасадори» v1.10.4 — 💙 Донати, Реєстрації та UI

v1.10.4 — функціональний та UX-реліз поверх v1.10.3. Він додає фінансову прозорість через Monobank, окрему чергу нових реєстрацій, фото можливостей і пакет виправлень адаптивності/темної теми, не прибираючи захист цілісності даних v1.10.3.

## Що нового у v1.10.4

- **📝 Реєстрації** стали окремою вхідною чергою: очікують / схвалено сьогодні / відхилено, перегляд, схвалення та відхилення з аудитом.
- Після схвалення профіль активується, учаснику надсилається Telegram-повідомлення, а запис переходить у **👥 Учасники**.
- Telegram отримав **💙 Підтримати** з банкою Monobank `https://send.monobank.ua/jar/5S531LWQuc` і **📄 Звітністю**.
- Web отримав **💙 Донати**: стан банки, прогрес, транзакції, загальна/середня/найбільша сума, донатери за доступними даними, збір по днях, перегляди підтримки, витрати та публічні документи.
- Автоматична синхронізація Monobank використовує секретний `MONOBANK_TOKEN`; перша виписка охоплює останні 31 день, далі історія накопичується локально.
- Донат можна автоматично або вручну пов’язати з АМП-кодом. Додано системні донатні бейджі: **Мій перший донат, Мажор, Мафіозі, Меценат, Почесний спонсор АМП, Брюс Всемогутній**.
- **🌍 Можливості** підтримують фото.
- Для звичайних ролей малі агреговані значення вразливості приховуються; **суперадміністратор бачить точні агреговані числа**, але персональні списки конкретних категорій не формуються.
- Виправлено темну тему destructive-блоків, обрізання карток на вузьких екранах, розташування кнопок прав доступу і поведінку редактора прав після збереження.
- Залишено **один перемикач теми** у правому верхньому куті.
- Додатково українізовано видимі назви та підписи інтерфейсу.
- Схема БД: **52 таблиці**, зміни additive/idempotent.

Деталі оновлення: `SERVER_UPDATE_V1104.md`. Команди: `COMMANDS_V1104.txt`. QA: `TEST_REPORT_V1104.txt`.

---

## Архів релізу v1.10.3

# AMP XP / «АМПасадори» v1.10.3 — 🛡️ Data Integrity & Data Quality

v1.10.3 — P0 stability/data release поверх v1.10.2. Основний фокус: часовий `check-in/attendance window`, ручний audit-override, коректні attendance KPI, canonical-довідник населених пунктів і P0 regression tests.

## Що нового у v1.10.3

- Check-in відкривається за **60 хв до** події та закривається через **360 хв після** старту за замовчуванням; обидва значення змінюються у Runtime Settings.
- Attendance та event XP не можуть бути підтверджені поза вікном звичайним шляхом. У web доступний ручний override лише з причиною; дія журналюється в audit.
- Місячні/періодні звіти окремо рахують завершені, майбутні та поточні події. Майбутня помилкова attendance-строка не потрапляє у KPI відвідуваності.
- `Унікальні залучені` більше не збільшується лише через створення профілю.
- KPI розділено на **«за період»** та **«станом на дату формування»**.
- Додано таблицю `settlement_references` і canonical normalization населених пунктів; `Анисів`, `Анисiв`, `с.Анисів` зводяться до `Анисів`.
- На Dashboard додано **Data Quality** widget з дублями/неканонічними значеннями та безпечною нормалізацією.
- Аналітика, розсилки та Smart Opportunities використовують canonical settlement matching.
- Додано P0 behavioral tests для раннього/пізнього check-in, меж вікна, override, повторного check-in, double-XP і майбутньої події у monthly report.
- Схема БД: **48 таблиць** (нова additive-таблиця `settlement_references`).

Деталі оновлення: `SERVER_UPDATE_V1103.md`.

---

## Архів релізу v1.10.2 — 🧩 Granular Permissions & Telegram Home

v1.10.2 — **🧩 Granular Permissions & Telegram Home**. Реліз поверх v1.10.0.1 додає точкові права доступу для працівників і переробляє головний Telegram-екран учасника. Security/reliability, Notification Center, Smart Opportunities, Advanced Analytics, Participant 360 та runtime settings попередніх версій збережені. Деталі — `SERVER_UPDATE_V1102.md`.

## Що нового у v1.10.2

- **Granular permissions** замість залежності лише від ролей `coordinator/admin/superadmin`: окремі права на учасників, події, XP, звіти, sensitive export, розсилки, модерацію, активності, аналітику, Notification Center, гейміфікацію, аудит, System Health і налаштування.
- Superadmin у web `🛡 Безпека та права доступу` може видати персональний набір прав окремому web-акаунту або Telegram-працівнику та повернути права «за роллю».
- Superadmin залишається break-glass роллю з повним доступом; malformed explicit ACL працює fail-closed.
- Права застосовуються не лише до кнопок: middleware захищає прямі URL, search/dashboard показують лише дозволені сутності, а Telegram callbacks повторно перевіряються сервером.
- `participants.edit` дозволяє редагувати тільки базові нечутливі дані; sensitive profile/media/consents зберігають посилений захист.
- `reports.sensitive_export` реально керує розширеними експортами подій/донорських списків і журналюється.
- При зміні ролі Telegram-працівника його старий custom ACL скидається, щоб попередні підвищені права не пережили зміну ролі.
- Telegram `🏠 Головна` перероблена в «Мій АМП сьогодні»: звертання по **імені**, AMP-ID/роль, XP до наступного рівня, wallet XP, ліга/сезон, streak, волонтерські години, найближча подія, дедлайн квесту, оновлення звернень і нові Smart Opportunities.
- `🤝 Запросити друга` та `🆘 Звернення` винесені безпосередньо в основне меню, а не заховані в другому рівні.
- БД: **47 таблиць**; нових таблиць немає. Додаються лише additive/idempotent `users.staff_permissions_json` і `web_staff_accounts.permissions_json`.

---

# AMP XP / АМПасадори v1.10.0.1

v1.10.0.1 — **🧪 Full Regression Alignment Hotfix**. Це QA/compatibility patch поверх v1.10.0: історичні regression-тести синхронізовано з канонічним Notification Center v1.9+, персоналізованими Smart Opportunities v1.9.2 та runtime-config waitlist v1.10.0. Runtime business logic v1.10.0 не змінено; schema БД без змін. Деталі — `SERVER_UPDATE_V11001.md`.

## Що виправлено у v1.10.0.1
- reliability regression тепер перевіряє канонічну таблицю `notifications`, `scheduled_at` і `retry_count`, а не legacy `notification_deliveries`;
- старий тест масової розсилки `opportunity_created` оновлено під Smart Opportunities: персоналізований matching + `opportunity_match`;
- waitlist regression більше не вимагає hard-coded `timedelta(hours=2)`: перевіряє runtime setting `events.waitlist_reservation_minutes` з default 120 хв;
- version/cache assertions усіх історичних regression-тестів синхронізовано з `1.10.0.1`.


v1.10.0 — **🎨 Major UX Refresh & ⚙️ Runtime Settings**. Telegram для учасника став компактним і task-oriented, головний екран показує «Мій АМП сьогодні», Participant 360 отримав послідовні іконки, а ключові правила XP/streak/events/privacy перенесено в web `⚙️ Налаштування` без потреби випускати код для кожної зміни. Усі функції v1.9.2 збережені. Деталі deployment — `SERVER_UPDATE_V1100.md`.

## Що нового у v1.10.0

- Компактне Telegram-меню з трьома хабами `Долучитися / Мій профіль / Ще`.
- «Мій АМП сьогодні» після входу: XP, рівень, streak, найближча подія, quest deadline, звернення і Smart Opportunities.
- Participant 360: іконка в кожній вкладці.
- Runtime Settings для XP, streak, events і privacy; редагування тільки superadmin + audit.
- Налаштування застосовуються автоматично до birthday/idea/referral XP, streak restore, freeze/miss/badge rules, reminders, feedback, waitlist та suppression threshold у аналітиці/звітах.
- БД: **47 таблиць**, нових schema migrations немає; runtime values використовують `system_settings`.

---

# AMP XP / АМПасадори v1.9.2

v1.9.2 — **🌍 Smart Opportunities & 🏆 Seasons History**. Реліз персоналізує каталог можливостей і перетворює сезони на повноцінну історію досягнень. Notification Center, Advanced Analytics, Outcomes, Participant 360, security/reliability та всі workflow v1.9.1 збережені. Деталі deployment — `SERVER_UPDATE_V192.md`.

## Що нового у v1.9.2

- Учасник сам обирає інтереси для можливостей: Волонтерство, Освіта, Гранти, Обміни, Підприємництво, Культура, Спорт, IT, Медіа.
- Matching враховує лише доречні операційні фактори: **вік, явні інтереси, населений пункт, формат і дедлайн**. Категорії вразливості для автоматичного profiling не використовуються.
- Telegram показує персональні match %, а Notification Center надсилає digest до трьох нових релевантних можливостей із dedupe-захистом.
- Web дозволяє таргетувати opportunity за напрямом/віком/форматом/населеними пунктами та бачити match count.
- Після завершення сезону зберігається історичний snapshot: TOP-3, переможці 6 ліг, рекорди XP/streak/волонтерських годин, бейджі, статистика і повний leaderboard.
- `🕰 Історія сезонів` доступна в Telegram-профілі й Participant 360; web має окрему сторінку деталей сезону.
- Startup поважає активний/архівний стан сезону і не реактивує завершені сезони.
- Схема БД: **47 таблиць**; міграція additive/idempotent і не вимагає повторного переносу PostgreSQL.

---

# АМП XP / «АМПасадори» v1.9.1

Актуальний реліз: **v1.9.1 — 📊 Advanced Analytics & PDF Layout Fixes**.

# AMP XP / «АМПасадори»

v1.9.0 — **🔔 Notification Center & Outcomes**. Усі proactive Telegram-сповіщення зведено до канонічної таблиці `notifications` і єдиного durable delivery/retry worker. У web додано `🔔 Сповіщення` з KPI, фільтрами та retry failed. Після підтверджених подій учасники отримують короткий feedback 1–5 + outcome-питання; результати потрапляють у per-event analytics, загальну аналітику та автоматичні Excel/PDF звіти з окремою сторінкою `Вплив`. Деталі deployment — `SERVER_UPDATE_V190.md`.

# AMP XP / «АМПасадори»

v1.8.2.5 — **🔔 Version Dedupe & Compact Telegram Admin Menu**. Виправлено повторні повідомлення про одну й ту саму версію за допомогою per-user/per-version UNIQUE outbox dedupe та завершення legacy version campaigns перед recovery. Telegram адмін-панель переведено на дворівневу структуру з коротким основним меню та role-aware підменю. Деталі deployment — `SERVER_UPDATE_V1825.md`.

# AMP XP / «АМПасадори»

v1.8.2.4 — **📷 Continuous Telegram Scanner & Version Notification Fix** поверх v1.8.2.3. Telegram QR Scanner переведено на Mini App/native QR popup: після вибору події камера відкривається всередині Telegram, не закривається після одного бейджа й дозволяє сканувати учасників послідовно. Кожен scan формує підтвердження в чаті бота для адміністратора. Також додано distributed lock для одноразового повідомлення про нову версію, щоб воно не дублювалося під час паралельного startup/deploy.

# AMP XP / АМПасадори v1.8.2.3

v1.8.2.3 — **📷 Telegram QR Scanner & Runtime Fixes** поверх v1.8.2.2. Виправлено runtime `Internal Server Error` у календарі, ідеях і зверненнях; QR Scanner перенесено в основний Telegram-admin workflow, а web отримав cross-browser перехід у Telegram. Схема БД і business logic попередніх релізів збережені. Деталі deployment — `SERVER_UPDATE_V1823.md`.

## Що нового у v1.8.2.3

- `📷 QR Scanner` додано безпосередньо в Telegram admin-панель для coordinator/admin/superadmin. Адміністратор обирає активну подію, сканує персональний QR-бейдж учасника камерою телефона та відкриває Telegram deep-link; бот одразу обробляє attendance.
- Якщо відсканований учасник не зареєстрований, Telegram показує `✅ Зареєструвати та підтвердити`. Підтвердження використовує чинний idempotent XP/attendance workflow та не дублює нагороду.
- Scanner mode також приймає `АМП-0008` або текст/посилання з персонального QR, тому є ручний fallback.
- На web-сторінці події основна кнопка `📲 QR Scanner у Telegram` працює незалежно від `BarcodeDetector`, тому доступна з Chrome, Safari, Firefox, Edge та мобільних браузерів. Browser-camera scanner залишено як додаткову можливість там, де API підтримується.
- Виправлено `Internal Server Error` у `📆 Календар`: Jinja більше не звертається до `dict.items` як до масиву; календар використовує окремий ключ `entries`.
- Виправлено `Internal Server Error` у `💡 Ідеї` та `🆘 Звернення`: workflow-константи статусів/категорій винесено в `ui_labels.py` і імпортуються явно.
- Прибрано дубль scanner JavaScript, який випадково потрапив у title-block сторінки події.
- Нових таблиць і міграцій немає; metadata залишається 44 таблиці.

---

v1.8.2.2 — **🩹 FastAPI/Pydantic startup hotfix** поверх v1.8.2.1. Функціональний patch поверх v1.8.2: єдиний календар День/Тиждень/Місяць, web QR Scanner на сторінці події, черга очікування з 2-годинним резервуванням місця та чіткий attendance workflow. Security, Participant 360, lifecycle, durable Telegram delivery та idempotent XP/attendance механіки попередніх релізів збережені. Деталі deployment — `SERVER_UPDATE_V1821.md`.

## Що нового у v1.8.2.1

- `📅 Календар` має режими **День / Тиждень / Місяць** і показує події, квести, волонтерські задачі, опитування, дедлайни можливостей, кейсів та ідей/мініпроєктів, а також freezes. Кожен тип має іконку й окремий візуальний акцент — інформація не залежить лише від кольору.
- На сторінці події додано `📷 Почати check-in`: камера телефона відкривається прямо у web через browser camera API та читає персональний QR учасника.
- Якщо відсканований учасник зареєстрований, система виконує check-in і підтвердження attendance через чинний idempotent workflow. Якщо не зареєстрований — адміністратор бачить `Зареєструвати та підтвердити`.
- Для подій з обмеженою місткістю додано **waitlist**. Коли місць немає, Telegram пропонує `⏳ Стати в чергу`.
- Після звільнення місця найстаріший учасник черги автоматично отримує **резерв на 2 години** і durable Telegram-повідомлення з кнопкою підтвердження. Прострочений резерв повертається в чергу, після чого місце переходить наступному.
- Attendance у web чітко розрізняє: `Зареєстрований`, `Скасував`, `У черзі`, `Місце зарезервовано`, `Відмічено присутність`, `Був присутній`, `Не прийшов`.
- Після завершення події непідтверджені `registered/reserved` автоматично переходять у `Не прийшов`.
- У `event_registrations` додано лише additive/idempotent поля waitlist/reservation/no-show; нових таблиць немає, загальна схема лишається 44 таблиці.

---

# AMP XP / АМПасадори v1.8.2

v1.8.2 — **🎨 Participant 360 UI Polish**. Це UI/UX patch поверх v1.8.1 без змін business logic і схеми БД. Виправлено відображення KPI та вкладок картки учасника, розділено квести й активності та прибрано дубль історії XP. Security, lifecycle, notifications, аналітика та всі workflow v1.8.1 збережені. Деталі deployment — `SERVER_UPDATE_V182.md`.

## Що нового у v1.8.2

- `🎯 Квести` та `⚡ Активності` — окремі вкладки Participant 360.
- 8 KPI відображаються компактною сіткою 4×2 на desktop.
- Центровані й вирівняні KPI, tabs і таблиці; довгі назви більше не накладаються на сусідні колонки.
- На вузьких екранах tabs прокручуються горизонтально, а KPI переходять у 2 колонки.
- Прибрано дубль таблиці останніх XP-операцій унизу; історія XP залишається у вкладці `XP`.
- Ручне нарахування XP збережене.
- Нових таблиць і міграцій немає.

---

# AMP XP / АМПасадори v1.8.1

v1.8.1 — **👤 Participant 360 & Lifecycle**. Реліз розвиває v1.8.0 Admin UX: додає повну 360° картку учасника, автоматичний життєвий цикл `deleted → restoration → 14-day probation → active / deleted_permanent`, автоматичні повідомлення про новий контент і розширену аналітику/звітність. Security v1.7.3, reliability/idempotency v1.7.4, event/referral/document-функції v1.7.4.1 та Admin UX v1.8.0 збережені. Деталі deployment — `SERVER_UPDATE_V181.md`.

## Що нового у v1.8.1

- `👤 Participant 360`: KPI, timeline, XP, події, квести/активності, волонтерство, ідеї, опитування, бейджі та документи на одній сторінці.
- Автоматичний soft-delete після 60 днів без активності зі збереженням усіх даних.
- Відновлення через Telegram-запит + рішення superadmin.
- 14-денний probation після відновлення; без підтвердженої участі — остаточне закриття доступу без повторного відновлення.
- `deleted` / `deleted_permanent` не доступні для ручного встановлення.
- Автоматичні Telegram-сповіщення активних учасників про нові події, квести, волонтерські задачі, активності, опитування та можливості.
- Розширені аналітика та звіти по життєвому циклу/залученню.
- `Health` у web UI має єдину назву `🩺 Стан системи`.

# AMP XP / АМПасадори v1.8.0

v1.8.0 — **🔔 Admin UX**. Реліз зосереджений на єдиному UX web-панелі та безпечній навігації Telegram під час FSM-форм. Security-база v1.7.3, reliability/idempotency v1.7.4 та функції v1.7.4.1 збережені. Деталі deployment — `SERVER_UPDATE_V180.md`.

## Що нового у v1.8.0

- Уніфіковано breadcrumbs/«шляхи» на всіх admin-сторінках, відступи, вирівнювання та базові action-кнопки.
- Dashboard отримав `🔔 Потребує уваги`: pending учасники, квести на перевірці, заявки активностей, прострочені звернення, нові ідеї, failed Telegram delivery та очікувані батьківські згоди — кожен пункт веде у відфільтрований список.
- Додано глобальний пошук у topbar: AMP-ID/ПІБ/username/населений пункт, а для superadmin також телефон/email; події, кейси, ідеї, квести, задачі, активності, можливості та опитування.
- Sidebar згруповано в `Огляд / Люди / Активності / Ініціативи / Гейміфікація / Комунікація / Система`; додано календар і сторінку налаштувань.
- Великі списки переведено на єдиний smart-filter UX `Пошук | Статус | Період | Тип | Сортування | Скинути`; значення пам’ятаються у `sessionStorage` окремо для кожного розділу.
- Під час будь-якої активної Telegram FSM-форми reply-menu кнопка більше не може стати відповіддю поля. Перед переходом показується `Так / Ні`; `Ні` зберігає поточний state/data, `Так` очищає форму та відкриває вибраний розділ.
- Додано автоматичну політику неактивності: попередження на 55-й і 59-й день без взаємодії, на 60-й день participant/ambassador переводиться у `inactive` і втрачає доступ. Заблоковані та staff-ролі не обробляються; дані/XP/історія фізично не видаляються.
- `🩺 Стан системи`: action-кнопки приведено до одного стандарту; failed durable Telegram deliveries можна повернути у retry одним натисканням.
- Додано 90-денний web-календар подій, дедлайнів квестів, волонтерських задач і можливостей.

# AMP XP / АМПасадори v1.7.4.1

v1.7.4.1 — функціональний patch-реліз поверх v1.7.4 Reliability & Architecture. Security-база v1.7.3 та distributed reliability/idempotency v1.7.4 збережені. Додано поширення/реєстраційні посилання подій, Telegram QR для check-in, donor registration templates DOCX/XLSX, SHA-256 коди підтвердженої участі, 30-денний referral clawback та новий каталог багаторазових винагород простору. Деталі deployment — `SERVER_UPDATE_V1741.md`.

## Що нового у v1.7.4.1

- Події отримали окремий `share_token`, публічну data-minimized сторінку та кнопку поширення у web/Telegram; share-token ніколи не є check-in token.
- У Telegram admin/superadmin можуть отримати публічне й пряме registration deep-link; coordinator/admin/superadmin — вибрати активну подію та завантажити PNG QR відмітки.
- До події можна прикріпити donor registration template `.docx` або `.xlsx`; експорт заповнює розпізнані колонки, намагаючись зберегти структуру/стилі. Якщо шаблону немає — використовується стандартний AMP Excel.
- Після admin-confirm attendance створюється унікальний 64-символьний SHA-256 confirmation code для конкретної участі. Це внутрішній технічний доказ/ідентифікатор, а не КЕП.
- Referral XP автоматично сторнується один раз, якщо запрошений активований учасник стає `inactive` протягом 30 днів після reward; inviter отримує durable Telegram notification. Telegram `Forbidden` під час outbox/broadcast також переводить participant/ambassador у inactive і запускає цю перевірку.
- Додано 9 дефолтних сервісних винагород 5–150 XP; `service` rewards можна замовляти повторно після виконання попередньої заявки.
- У виборі напряму ідеї обрана inline-кнопка залишається видимою як `✅` вибір перед переходом до наступного кроку.
- Регресійний набір розширено з 14 до 18 тестів.

# AMP XP / АМПасадори v1.7.4

v1.7.4 — технічний реліз Reliability & Architecture. Основний функціонал v1.7.3 збережено; додано автоматичні тести критичних workflow, розподілені DB-lock для scheduler/job, надійну Telegram retry-чергу, retry розсилок, окремий web-розділ `🩺 Стан системи` та фізичне розділення feature routes з великого `web/app.py`. Деталі deployment — `SERVER_UPDATE_V174.md`.

## Що нового у v1.7.4

- `tests/`: автоматичні тести реєстрації, подій, квестів, волонтерства, активностей, опитувань, ідей, кейсів, streak/freeze/restore, broadcast retry, scheduler locks і повторної міграції.
- `app/web/routes/`: feature routes винесено з монолітного `app/web/app.py` у окремі модулі dashboard/users/events/quests/tasks/activities/ideas/requests/surveys/analytics/reports/broadcasts/gamification/opportunities/system.
- `scheduled_jobs`: DB-lease не дозволяє двом процесам одночасно виконувати одну scheduler-задачу.
- `notification_deliveries`: надійна Telegram outbox-черга з повторними спробами через 1/5/15 хв та фінальним статусом `failed`.
- Розсилки отримали retry-лічильник та повторні спроби замість втрати одержувача після тимчасової помилки Telegram.
- `🩺 Стан системи`: Bot, DB, scheduler, version/release, pending/failed jobs, Telegram retry, broadcasts, storage, останні job/backup-marker.
- Схема БД зростає з 42 до 44 таблиць; міграція additive/idempotent.

# АМП XP / «АМПасадори» v1.7.2

Telegram-бот + web-панель для Анисівського молодіжного простору: учасники, XP, події, квести, волонтерські задачі, активності, ідеї, звернення, розсилки, винагороди, бейджі та аналітика.

## Що нового у v1.7.2

- Telegram `🔥 Серії участі` із самостійною заморозкою в межах квартальної квоти.
- Окрема web-сторінка редагування серій конкретного учасника.
- 6 ліг, включно з новою `👑 Легендарною` від 1500 XP; TOP-10 ліг у сітці 3×2.
- Покращений UX опитувань і multiple-choice без дублювання повідомлень.
- Більше способів вимірювання цілей та автоматичних бейджів.
- Web-підтвердження нових реєстрацій.
- Брендовані PDF/Excel списки учасників подій і поліпшені автоматичні звіти.
- Без нових таблиць/полів БД відносно v1.7.1.

## Що нового у v1.7.1

- Уніфіковано breadcrumb/«шлях» у ключових web-розділах і вирівняно ширини, відступи та KPI-картки, зокрема у `Опитування` та `Рейтинг і серії`.
- Опитування: повний Excel/PDF-експорт, PNG результату кожного питання, деталізація відповідей кожного респондента, фото до питання з показом у Telegram.
- Серії: адміністратор може заморозити серію на N днів; сумарний ліміт — 14 днів на календарний квартал. Заморожені дні не спалюють тижневу/подієву серію.
- У `Аналітика` додано проходження опитувань по тижнях, видані бейджі по тижнях, розподіл ліг та стан серій/заморозок.
- Автоматичний звіт АМП доповнено бейджами, лігами, серіями та використаними днями заморозки; Excel отримав окремі аркуші і графіки.
- Темна/світла тема та responsive-верстка нових секцій додатково уніфіковані.

## Що нового у v1.7.0

- повідомлення відповідальному за ідею/звернення з Telegram-кнопкою `Детально`;
- сезонні ліги і два рейтинги: загальний ТОП-20 та ТОП-10 своєї ліги;
- тижнева серія активності та суперсерія відвідування подій;
- автоматичний бейдж за 30+ днів суперсерії;
- спеціальна XP-винагорода для відновлення втраченої суперсерії;
- web-розділ `Рейтинг і серії` з аналітикою, модерацією, ручною корекцією та перерахунком з історії.

## Що нового у v1.6.9

- Новий web/Telegram модуль **📋 Опитування**: питання, дедлайн, XP, результати та автоматичне сповіщення після публікації.
- Статуси подій: чернетка, відкрита/закрита реєстрація, перенесено, завершено, скасовано.
- У `🤝 Запросити друга` додано PNG QR-запрошення.
- Зміни статусу учасників від звичайних адмінів підтверджуються суперадміністратором; є окрема черга очікування.
- Виправлено темну тему звітів, layout ідей та відступи/вирівнювання у зверненнях, розсилках, модерації й бейджах.
- До автоматичних звітів додано показники опитувань.
- Для вже зареєстрованих людей роль можна змінювати без дубля профілю через `scripts/promote_existing_user.py`.

## Що нового у v1.6.8

- Активності: до текстового результату учасник може додати фото/скріншот; доказ видно та можна керовано замінити у web.
- Бейджі: web-створення загальних і АМПасадорських бейджів, PNG із прозорістю для АМПасадорських та пакетна видача кільком учасникам.
- Події: автоматичне одноразове нагадування зареєстрованим учасникам приблизно за 1 годину до початку.
- Ідеї: +10 XP автору за перше схвалення; кольорові етапи шляху ідеї.
- Telegram: кнопки «Назад» у переглядах, але не всередині кроків введення даних.
- Цілі & місії: власний текст завдання, метрика, цільове значення, дедлайн, XP-нагорода, опис і фото; сезонні місії рахуються особисто, командні — спільно для АМПасадорів; нагорода видається один раз.
- Документи та згоди: статус/дата/скан батьківської згоди для неповнолітніх, версія й дата фото/відеозгоди, історія зміни та відкликання.
- Чутливі файли згод у production доступні лише суперадміністратору; у локальному режимі зберігаються поза публічною папкою uploads.



## Що нового у v1.6.7

- У Telegram повні назви подій, квестів, активностей, волонтерських задач і можливостей більше не обрізаються кодом.
- Ключові списки перебудовано: повна назва + дата/XP/місця показуються в тексті, а кнопки залишені по одній у рядку з максимальною шириною під назву.
- Виправлено структуру відступів у повідомленнях цих розділів.
- Видима назва персонального QR-розділу — **🎫 Мій QR-бейдж**. Старі назви підтримуються лише для сумісності; натискання старої кнопки оновлює головне меню.
- База даних не змінюється.


## Що нового у v1.6.6

- Квести після дедлайну автоматично отримують статус **«Завершено»**; старі Telegram-кнопки після дедлайну не спрацьовують.
- Стабілізовано й вирівняно web-блоки керування волонтерськими задачами.
- У Telegram скорочено довгі кнопки без трьох крапок наприкінці.
- **🎫 QR-бейдж**: окреме меню, фото до 20 МБ, красивий друкований PNG 55×85 мм / 300 DPI, завантаження та поширення.
- **Ідеї → міні-проєкти**: відповідальний, команда, дедлайн, бюджет/ресурси, завдання, прогрес, результат і фото.
- **Звернення → кейси**: номер AMP-РІК-XXXX, категорія, пріоритет, відповідальний, дедлайн відповіді, переписка, вкладення та повний workflow статусів.

## Що нового у v1.6.5

- Глобальне виправлення Telegram FSM: кнопки головного меню більше не потрапляють у відповіді незавершених форм.
- Статус учасника **Неактивний** із повним збереженням історії та XP.
- Автоматичне завершення прострочених подій, квестів, волонтерських задач і можливостей.
- Статус **Перенесено** з новою датою/часом, обов'язковою причиною та автоматичним повідомленням учасників.
- Самостійне скасування участі у подіях, квестах і волонтерських задачах; аналогічна дія доступна адміністратору у web.
- **📄 Звіти**: місяць / кілька місяців / квартал / рік → Excel або брендований PDF.
- **🏁 Цілі & місії**, streak активних місяців та прогрес до наступного рівня у Telegram.
- Повноцінний web-каталог **🌍 Можливості** з віком, дедлайном, посиланням, форматом, напрямом та обліком `Мені цікаво`.
- У **📊 Аналітиці** додано PNG для всього dashboard і кожного окремого графіка.
- Нові таблиці `goals`, `opportunity_interests` та сумісна автоматична міграція production-схеми.

## Що нового у v1.6.4

- Окремий dashboard **📊 Аналітика** з автоматичним розрахунком даних.
- Графіки: нові учасники, активність 30/90, відвідування, середня відвідуваність, волонтерські години, вік, стать, населені пункти, джерела XP, ідеї, агреговані категорії вразливості.
- Для кожного графіка: **Детально / Excel / PDF**.
- Загальний Excel містить зведення, окремі аркуші та Excel-графіки; загальний PDF містить зведення та окрему сторінку для кожного графіка.
- У Telegram-адмінці є спрощене зведення аналітики.
- Категорії вразливості ніколи не розкривають ПІБ або контакти у модулі аналітики.

## Що нового у v1.6.3

- Скасування/видалення подій, квестів і волонтерських задач із причиною та автоматичним повідомленням учасників.
- Автоматичне повідомлення активних учасників після розгортання нової версії.
- Власні шаблони у комунікаційному центрі «Розсилки».
- Безпечне додавання персональних web-admin акаунтів через `scripts/add_staff_account.py`.


## Що нового у v1.6.2

- Додано окремий web-розділ **📣 Розсилки / Комунікаційний центр** для суперадміністратора.
- Аудиторії: усі активні учасники, лише АМПасадори, довільна вікова група, населений пункт, учасники конкретної події, а також користувачі, які давно не взаємодіяли з ботом.
- Додано готові шаблони: нагадування про подію, привітання, новий квест, нова можливість.
- Перед відправкою обов’язковий попередній перегляд із кількістю одержувачів та прикладом персоналізованого повідомлення.
- Підтримуються токени `{first_name}` і `{full_name}`.
- Масова відправка виконується у фоні, щоб web-запит не залежав від кількості одержувачів.
- Додано історію кампаній і статус кожного одержувача: очікує / доставлено / помилка.
- Незавершені кампанії відновлюються після restart/deploy і продовжуються лише для ще не оброблених одержувачів.
- Telegram-адмінка більше не запускає небезпечну «розсилку всім» напряму: для суперадміна вона відкриває захищений web-комунікаційний центр.
- Додано `users.last_activity_at`; кожна взаємодія з Telegram-ботом оновлює її для фільтра «давно не були активні».


## Що нового у v1.6.1

- Виправлено картку поточного адміністратора в боковому меню: без білого фонового блока.
- У деталях події заголовок «Учасники події» тепер зліва, кількість — поруч із заголовком.
- Кнопки «Базовий Excel» і «Розширений Excel» розміщені справа зверху в блоці учасників.
- Для скасованої реєстрації можна видалити запис учасника зі списку події; інші статуси видалити цією дією неможливо.
- Видалення скасованої реєстрації записується в журнал аудиту.


## Що нового у v1.5.9

- Реєстраційна анкета в Telegram тепер не дозволяє пропускати жоден етап.
- Прізвище та ім’я потрібно вводити з великої літери; неправильне значення не переводить користувача до наступного кроку.
- Телефон, email, населений пункт і дата народження обов’язкові та проходять базову валідацію.
- Соціальний статус / категорії також є обов’язковим кроком з можливістю обрати кілька номерів через кому.
- Додані статуси «Місцевий житель/жителька» та «Не відношусь до жодної з перелічених категорій».
- «Інша категорія» вимагає текстового уточнення.


## Що нового у v1.5.4

- Уніфіковано всі поля завантаження фото: замість нестабільного системного Safari-контролу використовується однаковий web-компонент «Обрати файл» + назва вибраного файлу.
- Вирівняно редактори подій, квестів і волонтерських задач: фото займає повну ширину, чекбокс видалення фото не стискається, кнопка збереження стоїть по сітці.
- На сторінці ідеї «💾 Зберегти картку ідеї» та «🗑 Видалити ідею» стоять паралельно; на вузьких екранах — одна під одною.
- Фото звернення та керування ним відцентровані. У винагородах завантаження фото й перемикач доступності також вирівняні.
- Форму бейджів вирівняно; напис «Видавати автоматично» не розривається всередині слова.
- У деталях журналу дій виправлено маршрут сторінки: елементи breadcrumb мають чіткі проміжки й не накладаються.



## Що нового у v1.5.2

- Вирівняно кнопки «👁 Детально» та «✏️ Редагувати» у картках подій, квестів і волонтерських задач: однакова висота, ширина та вертикальне центрування.
- Для квестів і волонтерських задач дедлайн у web-панелі вводиться окремо: день, місяць, рік і час — за тією ж логікою, що й у подіях.
- У Telegram-адмінці створення квестів і волонтерських задач також збирає день, місяць, рік і час окремими кроками.
- Картки квестів і волонтерських задач приведено до єдиного стилю з подіями: фото без обрізання, дата/час у плашці, факти та рівні кнопки.
- На детальній сторінці ідеї прибрано будь-які переходи чи блоки модерації. Залишено тільки окрему кнопку «🗑 Видалити ідею».
- Додано адаптивні правила для форм дати/часу та карток на планшетах і телефонах.

## Що нового у v1.5.1

- Події: дата у web-формі розділена на **день / місяць / рік / час**; у Telegram створення події теж проходить цими кроками.
- Картки подій перероблено: стабільна сітка, окремі плашки дати/XP/годин/місткості, акуратний редактор без «плаваючих» блоків.
- Додано окремий великий розділ **🛡 Модерація** у web-панелі. Бан прив’язаний до профілю людини, а не до ідеї чи іншого контенту.
- У модерації доступні: видати тимчасовий бан, переглянути активні бани, скоротити строк, достроково зняти бан, переглянути повну історію та причини.
- Додано таблицю `ban_records`; історія модерації не зникає після завершення бану. Старі активні блокування автоматично переносяться в новий журнал.
- У Telegram-адмінці суперадміністратора додано **🛡 Модерація** з тими самими базовими діями та історією.
- Блокування прибрано з картки ідеї; у картці учасника залишено лише посилання до централізованого модуля модерації.

## Що було додано у v1.5.0

- Детальні сторінки квестів зі списком учасників та підтвердженням виконання.
- Волонтерські задачі для кількох учасників: максимальна кількість місць, фото, список виконавців, індивідуальне підтвердження.
- Видалення ідей та тимчасове блокування порушників.
- Фото до звернень із Telegram та web.
- Професійніший блок звернень.
- Breadcrumb-навігація без злиття назв сторінок.

## Постійне сховище

За замовчуванням усі робочі дані зберігаються у:

```text
~/AMP_Bot_Data/
├── amp_bot.db
├── uploads/
│   ├── events/
│   ├── quests/
│   ├── tasks/
│   ├── requests/
│   └── rewards/
└── backups/
```

Тому закриття програми або перехід на нову версію **не видаляє базу і фото**.

## Оновлення з v1.5.3

Скопіюйте лише `.env` у папку нової версії. Базу та фото вручну копіювати не потрібно, якщо вже використовується `~/AMP_Bot_Data`.

```bash
cp ~/Downloads/amp_bot_v153/.env ~/Downloads/amp_bot_v154/.env
cd ~/Downloads/amp_bot_v154
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_all.py
```

Web-панель:

```text
http://localhost:8080/admin
```

Після оновлення CSS зробіть `Cmd + Shift + R`.

## Звернення з фото

Telegram-сценарій:

`тип → тема → опис → Чи маєте фото? → Так/Ні → фото (за потреби) → створення звернення`.

Фото зберігається у постійній папці даних та доступне на детальній сторінці звернення у web.

## Волонтерські задачі

Адміністратор задає кількість місць. Учасники долучаються до задачі незалежно один від одного. Після виконання кожен надсилає виконання на перевірку, а адміністратор підтверджує кожну участь окремо. Після підтвердження автоматично нараховуються XP і волонтерські години.

### Зміни v1.5.3
Web UI отримав єдину систему контролів форм: текстові, числові, часові поля, випадаючі списки й textarea мають однакову геометрію та стани. У довідці вирівняно вертикальний ритм, а редагування бейджів тепер відкривається через стандартну кнопку інтерфейсу.


## Excel учасників події (v1.5.9)
У деталях кожної події є окрема кнопка завантаження Excel зі службовою інформацією про подію та списком зареєстрованих учасників. Файл містить персональні дані й призначений лише для уповноваженої команди АМП.

## Захист персональних даних у web (v1.6.0+)

Поточні `WEB_ADMIN_USERNAME` і `WEB_ADMIN_PASSWORD` використовуються як облікові дані **суперадміністратора**. Він бачить повну картку учасника, може редагувати персональні дані, користуватися модерацією, журналом доступу і розширеним Excel.

Додаткові працівники можуть входити як звичайні адміністратори через `WEB_STAFF_ACCOUNTS_JSON`. Приклад у `.env`:

```env
WEB_STAFF_ACCOUNTS_JSON={"ivan":{"password":"CHANGE_ME_1","display_name":"Іван Галуза"},"elizaveta":{"password":"CHANGE_ME_2","display_name":"Єлизавета Аткочунас"}}
```

Для таких облікових записів телефон і email маскуються, а дата народження, стать, Telegram ID і категорії вразливості не показуються. Кожне відкриття картки фіксується у журналі.

### Excel
- `📥 Базовий Excel` — робочий експорт без чутливих контактних і соціальних даних.
- `🔐 Розширений Excel` — лише для суперадміністратора; містить повні персональні поля та журналюється.

### Щоденний Heroku Postgres backup

Після деплою один раз виконайте:

```bash
./scripts/heroku_schedule_backups.sh amp-bot-ver-1-5-0 "03:00 Europe/Kyiv"
```

Перевірка:

```bash
heroku pg:backups:schedules --app amp-bot-ver-1-5-0
```
