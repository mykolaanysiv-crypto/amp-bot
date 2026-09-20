# v1.17.0.4 — Event Commitment XP

- Події мають три окремі налаштування мотивації: базовий XP за фактичну участь, бонус XP за попередню реєстрацію + участь та штраф XP за неявку без скасування.
- Попередня реєстрація визначається за фактичним часом реєстрації до старту події; реєстрація на вході через scanner не отримує бонус.
- Після завершення події статус `Не прийшов` автоматично застосовує налаштований штраф XP рівно один раз.
- Учасник може самостійно скасувати реєстрацію лише до початку події; чергу очікування можна залишити окремо.
- Нагадування та картки подій пояснюють бонус, дедлайн скасування та наслідок неявки.
- Суперадміністратор у деталях події може вручну встановити будь-який статус реєстрації незалежно від дати й часу; XP та волонтерські години автоматично узгоджуються з новим статусом, а зміна журналюється.
- Додано міграцію Alembic `20260920_0008_event_commitment_xp`.

---

# v1.17.0.3 — Manual Event Feedback Resend

- У детальній картці події в блоці «⭐ Зворотний зв’язок та вплив» додано кнопку **«🔁 Повторно надіслати відгук»**.
- Розсилка йде лише підтвердженим учасникам (`attended`) з активним Telegram-профілем, які ще не завершили мікровідгук.
- Якщо відгук ще не був створений автоматичним scheduler, ручна дія створює його та надсилає перше питання; якщо учасник уже почав відповідати — надсилається саме наступне незавершене питання.
- Завершені анкети не отримують повторних повідомлень. Повторний клік у межах однієї хвилини дедуплікується, щоб захистити від випадкових подвійних відправок.
- Після запуску Web показує кількість повідомлень, поставлених у Notification Center/outbox; дія журналюється в аудиті.
- База даних і Alembic не змінюються; head залишається `20260919_0007`.

# v1.17.0.2 — Giveaway Draw UX Hotfix

- Прибрано raw JSON / HTTP 409 зі сторінки після очікуваних перевірок під час запуску розіграшу.
- Додано спільну перевірку `_draw_block_reason` для GET/POST, щоб логіка доступності кнопки і серверна валідація були однаковими.
- Якщо дедлайн ще не настав, адміністратор бачить зрозуміле попередження з часом дедлайну та підказкою «⏹ Закрити» для дострокового проведення.
- Кнопка запуску приховується, якщо розіграш у чернетці/скасований, немає призів або недостатньо допущених учасників.
- Після успішного проведення показується in-app підтвердження; raw JSON більше не використовується для очікуваних бізнес-помилок розіграшу.
- База даних і Alembic не змінюються.

# v1.17.0.1 — QR badge scanner hotfix

- Виправлено POST URL Telegram Mini App QR-сканера: кириличний фрагмент `/tg/event-сканер/...` замінено на канонічний `/tg/event-scanner/...`, тому скан бейджа знову доходить до backend і змінює статус реєстрації на `attended` через штатний idempotent workflow.
- Після успішного сканування камера коротко закривається, на екрані показується явне повідомлення `✅ Код скановано успішно` з ПІБ та результатом, після чого камера автоматично відкривається для наступного бейджа.
- Лічильник `Відмічено` збільшується лише коли присутність фактично підтверджена; незареєстрований учасник показується як попередження, а не як успішна відмітка.
- Додано regression guard, який забороняє повернення кириличного URL маршруту в шаблон сканера.

# v1.17.0 — Giveaways & Auditable Randomizer

- У Web → «Гейміфікація» додано окремий розділ **🎲 Розіграші** з повним lifecycle: чернетка, активний, закритий, проведений, скасований.
- Підтримано аудиторії: усі активні користувачі, команда АМП, учасники конкретної події, обрані ролі або конкретні користувачі.
- Два режими участі: **автоматичний** за аудиторією або **завдання + обов’язкове фото-підтвердження** до дедлайну.
- Для task-розіграшів адміністратор перевіряє підтвердження та може допустити, повернути на доопрацювання або відхилити. До рандомайзера потрапляють лише підтверджені учасники, які досі входять у цільову аудиторію.
- До одного розіграшу можна додати до **5 типів подарунків**; кожен має назву, опис, фото і кількість одиниць. Загальна кількість одиниць = кількості переможців.
- Автоматичний рандомайзер використовує криптографічний seed + детермінований SHA-256 порядок, зберігає seed/алгоритм для аудиту та не дозволяє непомітно перезапустити вже проведений розіграш. Один учасник може виграти максимум один подарунок у межах одного розіграшу.
- Після розіграшу під кожним подарунком Web показує фактичних переможців; кожному переможцю через Notification Center/outbox автоматично надсилається Telegram-повідомлення про виграш.
- У Telegram → «Мій профіль» додано **🎲 Розіграші**. Учасник бачить лише активні й доступні йому розіграші, статус автоматичної участі або стан поданого підтвердження.
- Для task-розіграшу Telegram збирає текст виконання і **обов’язкове фото**; фото зберігається як staff-private media. Фото подарунків класифіковано як public media.
- Дедлайни розіграшів проходять через canonical `Clock`: Web `datetime-local` конвертується з Europe/Kyiv у canonical UTC storage, а відображення повертається у локальний час.
- Alembic `20260919_0007`: таблиці `giveaways`, `giveaway_prizes`, `giveaway_entries`, `giveaway_winners`. Metadata: **61 таблиця**.

# v1.16.0 — Team Tasks & Restricted Team Events

- Вкладка «АМПасадори» розширена до повноцінної команди АМП: у списку є АМПасадори, координатори, адміністратори та суперадміністратори.
- Додано персональні «Завдання для команди»: виконавець, опис, дедлайн, XP, обов’язковий текстовий звіт, необов’язкове фото, перевірка/повернення/скасування та idempotent нарахування XP лише після підтвердження.
- Telegram «Кабінет команди АМП» доступний ролям ambassador/coordinator/admin/superadmin; звідти можна переглядати свої завдання й подавати звіти.
- Події отримали `access_scope=general|team`. Team-події використовують існуючий lifecycle, реєстрацію, waitlist, QR/check-in, attendance, XP, feedback та аналітику, але видимі й доступні лише командним ролям.
- У Telegram для командних ролей розділ «Події» має дві категорії: «Загальні події» та «Події для АМПасадорів»; звичайні учасники бачать лише загальні.
- Закриті team-події не мають публічної share-сторінки й не розсилаються звичайним учасникам.
- Виправлено зламану кнопку «Поділитися» на детальній сторінці можливості: JavaScript більше не вставляється у HTML через `tojson` всередині атрибута.
- Кнопки «Редагувати» у Web-панелі приведені до спільного стилю `edit-action-button`.
- Alembic `20260919_0006`: таблиця `team_tasks` + `events.access_scope`. Schema: 57 таблиць.
- Синхронізовано `HEROKU_DEPLOY.md` з фактичним безпечним release-order: db.init → Alembic → bootstrap → lifespan.

# v1.15.1 — Survey & Opportunity Management UX

- Опитування: замість незручного multi-select додано пошук учасників, checkbox-картки, лічильник вибраних, «Обрати показаних» і «Очистити»; блок «Оберіть подію» вирівняно з іншими полями.
- Винагороди: додано видалення; винагороди з історією отримання не стираються фізично, а деактивуються для збереження аудиту.
- Бейджі: додано видалення загальних, системних і АМПасадорських бейджів разом із присвоєннями. Для вбудованих бейджів зберігається tombstone, тому bootstrap не створить їх повторно.
- Можливості: основний борд переведено на компактні картки однакового формату без повного опису; додано окрему сторінку «Детально».
- Детальна сторінка можливості: повний опис, дедлайн/статус, базова аналітика, перегляди, зацікавлені, персональні збіги, публічне посилання, share, редагування, перенесення дедлайну, публікація/приховування, оновлення збігів і видалення.
- Додано публічну share-сторінку можливості.
- Alembic `20260918_0005`: стабільний `badges.seed_key` для надійного видалення seeded-бейджів. Кількість таблиць не змінюється: 56.

# v1.15.0.1 — Donation Badge CI Hotfix

- Відновлено явний український маркер «Системний донатний бейдж» у Web-каталозі бейджів.
- Historical v1.15 regression test більше не прив’язаний до одного patch-номера, але перевіряє узгодженість VERSION.txt / VERSION_CHECK.txt.
- У test_v1741 прибрано deprecated datetime.utcnow() на користь canonical Clock, щоб Python 3.13 не генерував зайві warning.
- Production preflight тепер контролює наявність українського маркера системного донатного бейджа.
- Схема БД не змінюється; Alembic head залишається 20260918_0004.

# v1.15.0 — Targeting, Event Analytics & Opportunity UX

- Опитування отримали цільові аудиторії: всі активні, обрані учасники або учасники конкретної події.
- Звіти використовують зрозумілий український формат тижня «понеділок–неділя» з датами.
- У картці події додано базову event-level аналітику.
- Можливості автоматично сортуються за актуальністю/дедлайном; за 3 дні до дедлайну Web і Telegram показують 🔥-попередження.
- Відповідальний за кейс обмежений ролями superadmin/admin/coordinator/ambassador.
- Дозволено редагувати системні та АМПасадорські бейджі, водночас built-in business rules захищені від rule drift.
- Alembic `20260918_0004`: survey audience fields + `survey_audience_users`. Schema: 56 таблиць.

# v1.14.0.2 — Telegram Profile Import Hotfix

- Виправлено відкриття «👤 Мій профіль» у Telegram після v1.14.0: `participant_home.py` тепер явно імпортує `UserRole`, який використовується для відображення напряму відповідальності АМПасадора.
- Додано regression test і production-preflight guard, щоб профільний handler не міг знову посилатися на `UserRole` без explicit import.
- Функціональність v1.14.0.1, donation XP, кабінети АМПасадорів і Alembic head `20260917_0003` збережені без нової міграції.

# v1.14.0.1 — Release Schema Order Hotfix

- Виправлено Heroku release failure `UndefinedColumnError: users.ambassador_responsibility does not exist`.
- Production lifecycle тепер виконується у безпечному порядку: `db.init()` → Alembic `upgrade head` → `bootstrap_defaults()` → FastAPI lifespan.
- Додано production-preflight guard і regression test, які не дозволяють повернути ORM bootstrap перед schema migration.
- Функціональність v1.14.0, схема 55 таблиць і Alembic head `20260917_0003` збережені без нової міграції.

# v1.14.0 — Donations XP + Ambassador Cabinets

- Донатний XP: 1 XP = 5 грн, автоматичне зв’язування за АМП-кодом, idempotent та retroactive backfill.
- Telegram-кабінет АМПасадора: напрям відповідальності, звіти за період, фото.
- QR-код події для зареєстрованого АМПасадора.
- Web: новий розділ АМПасадорів для admin/superadmin, призначення напрямів і перегляд звітів.
- Alembic 20260917_0003: users.ambassador_responsibility + ambassador_reports.

# AMP XP v1.13.1 — Profile, Badges & Analytics UX

- Виправлено кнопку «⚡ XP» у «Мій профіль»: історія XP використовує canonical `XPTransaction.description`.
- Автоматичні бейджі тепер створюють Notification Center повідомлення «Вітаємо! Ви отримали новий бейдж» з причиною та кнопкою переходу.
- «🏅 Бейджі» спрощено до «Усі бейджі» / «Мої бейджі»; каталог показує умови отримання та вже здобуті бейджі.
- У профілі біля ПІБ показується 🔥 при активній суперсерії; підтримано optional animated Telegram custom emoji через `TELEGRAM_FIRE_CUSTOM_EMOJI_ID`.
- Вирівняно fixed topbar/search із фактичною шириною sidebar на laptop/desktop/large desktop; нормалізовано відступи карток та analytics controls.
- Графіки аналітики з dashboard відкривають детальний агрегований показник по кліку. На detail page суперадміністратор може клікнути точку/рядок і побачити тип агрегату, групу/категорію, значення та додаткове поле.
- Schema unchanged: 54 таблиці; Alembic head `20260915_0002`.

# AMP XP v1.13.0.4 — CI Localization & Test Time Hotfix

- Виправлено застарілий regression assertion Notification Center: `Streak` → `Серії участі`.
- Historical v1.13.0.3 version test зроблено patch-compatible для наступних `1.13.0.x`.
- Smart Opportunities regression test переведено з deprecated `datetime.utcnow()` на project `Clock` storage boundary.
- Синхронізовано `VERSION.txt`, `VERSION_CHECK.txt`, `app/version.py` та static asset cache tokens.
- Production code/schema unchanged; Alembic head `20260915_0002`.

# AMP XP v1.13.0.3 — Telegram Navigation & Web Localization Hotfix

## Виправлено
- Активні `/start` і `/menu` після Architecture Completion: виправлено lazy relative import `participant`; `/menu` знову відкриває актуальну «Головна» та оновлює reply-клавіатуру.
- Додано `/smart` як публічну Telegram-команду персональних можливостей із refresh matching.
- Винагороди більше не обрізають назви через `compact_button_text`.
- Локалізовано відомі англомовні назви web-панелі; Notification Center відображає відомі internal codes через українські labels.
- Додано v1.13.0.3 production preflight/regression guards і синхронізовано historical UI assertions.

## Сумісність
- Без schema migration; 54 таблиці; Alembic head `20260915_0002`.
- Architecture Completion v1.13.x зберігається без rollback.

---

# AMP XP v1.13.0.2 — Startup Import Hotfix

- виправлено неправильну package depth у `app/handlers/start_flow/common.py` після split `handlers/start.py`;
- виправлено lazy import `gamification` у `start_flow/entry.py`;
- додано загальний AST preflight для unresolved explicit relative module imports у `app/`;
- додано release asset-cache guard і синхронізовано `?v=1.13.0.2`;
- business logic, 54-table schema та Alembic head `20260915_0002` без змін.

# AMP XP v1.13.0.1 — Architecture CI Compatibility Hotfix

## CI / regression compatibility
- Додано `tests/source_layout.py` — єдина карта canonical source locations після Architecture Completion. Старі source-inspection regression tests більше не вимагають, щоб реалізація фізично залишалась у compatibility facades.
- Оновлено 32 regression checks, які після v1.13.0 помилково читали `app/main.py`, `app/models.py`, `app/web/app.py`, `app/web/routes/events.py`, `app/analytics.py`, `app/reports.py` або `app/handlers/start.py` замість нових domain modules.
- Event scanner AST regression тепер перевіряє canonical `app/web/event_routes/operations.py`; загальний FastAPI body-param guard сканує і `app/web/routes/`, і `app/web/event_routes/`.
- Notification Center regression allowlist оновлено для легітимного immediate Web 2FA path у `app/web/auth_routes.py`; business notifications і надалі повинні йти через canonical outbox.
- Version announcement regressions переведено на `app/web/broadcast_runtime.py` + lifespan ordering, а не на старий `app/web/app.py`.
- Historical v1.13.0 architecture test більше не exact-pin-ить patch version і перевіряє continuity всієї гілки `1.13.x`.

## Runtime / schema
- Runtime business logic не змінюється; hotfix виправляє CI assumptions після refactor.
- PostgreSQL schema: 54 таблиці, без змін.
- Alembic head: `20260915_0002`.
- Compatibility facades залишаються на заплановані 1–2 релізи; до них не повертається дубльована реалізація лише заради тестів.

---

# AMP XP v1.13.0 — Architecture Completion

## Composition roots
- FastAPI web composition переведено на `app.web.factory.create_app()`; `run_web.py` використовує Uvicorn factory mode.
- `app/web/app.py` лишився тільки compatibility facade на перехідні 1–2 релізи.
- Web dependencies, lifespan, health/auth/media routes та broadcast runtime винесені з моноліту в окремі модулі.

## Domain split
- `app/web/routes/events.py` → `app/web/event_routes/*`.
- `app/analytics.py` → `app/analytics_modules/{core,exports}.py`.
- `app/reports.py` → `app/reporting/{periods,builder,exports}.py`.
- `app/models.py` → `app/model_domains/*` із явним facade export; SQLAlchemy metadata залишилась ідентичною — 54 таблиці.
- `app/handlers/start.py` → `app/handlers/start_flow/*`.
- `app/main.py` → orchestration entry point; dispatcher/profile middleware винесені в `app/bot_runtime.py` / `app/telegram_middleware.py`; усі 13 scheduler — у `app/jobs/*`.

## Import hygiene / production guard
- У `app/` більше немає `import *`.
- Compatibility facades використовують explicit public exports.
- `production_preflight` перевіряє factory composition, split packages, facade-size limits, wildcard-import guard та Alembic/schema continuity.
- Startup smoke створює web app через canonical factory і додатково перевіряє legacy facade import.
- Schema migration у v1.13.0 відсутня; production Alembic head лишається `20260915_0002`.

---

# AMP XP v1.12.2 — Error & Time Hardening

## Час і DST
- Додано один canonical `Clock` (`app/time_utils.py`) з aware UTC, Europe/Kyiv local time, local-wall/legacy-storage adapters і DST-safe helpers.
- Application/scripts більше не використовують прямі `datetime.utcnow`, `datetime.now` або `date.today` поза Clock boundary; ORM defaults також централізовано.
- Check-in window порівнює aware UTC timestamps і повертає UTC diagnostic fields разом із legacy-compatible local-wall values.
- Birthday scheduler очікує локальні 09:00 через absolute UTC delta, тому spring/fall DST не додає/не віднімає зайву годину.
- Reporting 2.0 переводить local-calendar boundaries у UTC storage bounds; day/month/quarter/year selections коректні на midnight і DST transitions.
- Registration daily counters і season XP backfill використовують ті самі canonical UTC boundaries.

## Error hardening / observability
- Прибрано silent `except Exception: pass`; production preflight і regression test блокують повернення цього патерну.
- `JsonLogFormatter` підтримує `error_code` і структурований `context`; sensitive context keys редагуються, нестандартні values переводяться у bounded JSON-safe representation.
- Critical runtime/heartbeat/scheduler/broadcast/version/notification/backup error paths отримали стабільні error codes та context.
- Redaction filter більше не ковтає власну помилку мовчки: formatter може віддати `redaction_error` marker.

## Compatibility / schema
- Нова schema migration не потрібна.
- PostgreSQL лишається на 54 SQLAlchemy tables; Alembic head: `20260915_0002`.
- Legacy timestamp-without-time-zone storage не мігрується масово у цьому релізі: UTC/local semantics зафіксовані на persistence boundary через `Clock`.
- `VERSION.txt`, `VERSION_CHECK.txt`, static cache-busters, README/CHANGELOG/START_HERE/SERVER_UPDATE/TEST_REPORT синхронізовано до v1.12.2.

## QA
- `compileall`: PASS.
- `production_preflight`: PASS.
- v1.12.2 hardening tests: 8/8 PASS.
- focused v1.12.x regression suite: 49/49 PASS.
- Full local `pytest -q` у sandbox не завершено на collection через відсутній `aiogram`; authoritative full/integration suite лишається GitHub Actions із dependency install + PostgreSQL 16.

---

# AMP XP v1.12.1.7 — Event Open + Content Views + Cockpit UX

## Додано
- Generic `content_views`: загальні та унікальні Telegram-перегляди для подій, квестів, волонтерських задач, можливостей, активностей та опитувань.
- Alembic revision `20260915_0002`; metadata тепер 54 таблиці.
- Лічильники переглядів у web-картках та detail-екранах.

## Виправлено
- Відкриття події не падає через lifecycle-refresh, HTML parse mode або довгий photo caption.
- Квести й волонтерські задачі отримали такий самий lifecycle isolation під час відкриття.
- Event Operations Cockpit вирівняно за зовнішніми/внутрішніми відступами, висотою панелей, сіткою дій та mobile layout.

---

# AMP XP v1.12.1.6 — Health JSON Serialization Hotfix

## Виправлено
- `/health/dependencies` більше не повертає HTTP 500, коли runtime heartbeat містить `datetime`.
- HTTP health-відповіді проходять через FastAPI `jsonable_encoder` перед `JSONResponse`.
- Внутрішній runtime snapshot зберігає native `datetime`, тому адмін-логіка та внутрішні споживачі не змінені.
- Production preflight тепер перевіряє наявність datetime-safe JSON boundary.
- Historical v1.12.1.5 regression test зроблено сумісним із наступними patch-релізами.

## Без змін
- Схема БД, XP, Telegram UX, scheduler cadence та backup automation не змінювалися.

---

# AMP XP v1.12.1.5 — Backup Verification Automation Hotfix

## Виправлено
- новий production release без `last_backup_at` більше не надсилає false-positive backup alert одразу: діє 24-годинне initial grace window;
- статус `unknown` під час grace відображається як «очікує першої автоматичної перевірки», але система не видає його за справжню резервну копію;
- успішне підтвердження backup очищає bootstrap/alert markers;
- GitHub production deploy перед відправкою нового коду автоматично створює Heroku PGBackup, фіксує marker у AMP і перевіряє його;
- додано окремий GitHub Actions workflow `AMP Verified Backup` для щоденного та ручного verified backup;
- ручний helper `scripts/heroku_capture_verified_backup.sh` тепер також перевіряє marker після запису.

## Без змін
- схема БД, XP, Telegram UX і бізнес-логіка не змінені.

# AMP XP v1.12.1.4 — Domain Import Startup Hotfix

- Виправлено runtime-помилку release smoke: `app.domain_services.bootstrap` помилково імпортував `settlements` і `donations` як сусідні domain-модулі.
- Одночасно виправлено ще два приховані імпорти того самого класу: `gamification -> donations` та `events -> reliability`.
- Production preflight тепер AST-перевіркою відхиляє неіснуючі single-dot imports усередині `app/domain_services`, щоб подібний refactor-regression не доходив до startup.
- Схема БД, XP, права, Telegram UX та web-поведінка не змінені.

# AMP XP v1.12.1.2 — CI Compatibility & Emergency Alert Hotfix

- Виправлено historical regression tests, які помилково фіксували старий номер релізу `1.12.0` і ламали кожне наступне оновлення. Тепер вони перевіряють синхронність `VERSION.txt`, `VERSION_CHECK.txt` та cache-buster поточного релізу.
- Cache-buster web CSS/logo синхронізовано з v1.12.1.2.
- `app/runtime_health.py` формально закріплено як єдиний out-of-band emergency Telegram channel поруч із canonical Notification Center та Web 2FA. Він надсилає лише системні аварійні повідомлення `SUPERADMIN_IDS` і потрібен саме тоді, коли worker/Notification Center недоступний.
- Додано regression tests, щоб старі version assertions і emergency-channel allowlist більше не ламали Production Gate.
- Product behavior, БД і XP-баланс не змінювались.

# AMP XP v1.12.1.1 — Reward Catalog Refactor Hotfix

- Виправлено regression після розбиття `services.py`: каталог `DEFAULT_SPACE_REWARDS` не був перенесений у `app/domain_services/gamification.py`, через що повний GitHub CI падав у `test_default_space_rewards_seeded_as_repeatable_services`.
- Відновлено 9 стандартних винагород АМП із незмінними назвами, описами та XP-вартістю.
- Додано швидкий regression test каталогу, який не потребує БД, на додачу до наявного DB-test.
- Схема БД та зовнішня поведінка не змінені. Production Stability Gate спрацював правильно: дефект був заблокований до deploy.

---

# AMP XP v1.12.1 — Production Stability Gate

- Real release/startup lifecycle smoke: `db.init → bootstrap_defaults → Alembic → FastAPI lifespan`, plus worker import.
- PostgreSQL 16 CI integration/release smoke and deploy job gated by successful CI.
- New `/health/live`, `/health/ready`, `/health/dependencies`.
- Explicit PostgreSQL per-dyno pool limits and pool telemetry.
- Persistent web/worker/scheduler heartbeat, scheduler supervisor/restart and rate-limited superadmin alarms for stale/dead background processes.
- No schema delta: 53 tables; runtime markers use `system_settings`.

---

# v1.12.0.1 — Startup Bootstrap Hotfix

- Fixed production release failure `NameError: _bootstrap_lock is not defined` introduced by the v1.12.0 domain-service refactor.
- Restored the process-local `asyncio.Lock()` used to serialize startup seeding.
- No database schema changes; external bot/web behaviour is unchanged.
- Added regression coverage for release bootstrap.

# v1.12.0 — Codebase Refactor, Production Engineering & Gamification 2.0

- Services moved to `app/domain_services` behind a compatibility facade.
- Telegram admin/participant handlers split into smaller domain modules.
- Alembic baseline adopted; legacy upgrader remains transitional only for pre-v1.12 compatibility.
- Heroku web/worker process separation.
- GitHub CI + PostgreSQL integration test + release preflight.
- Structured JSON logs, request IDs, secret redaction, optional Sentry.
- Failed Notification Center and stale-backup superadmin alerts.
- Verified backup helper/marker.
- Gamification 2.0 analytics with a persisted clean-data baseline and no automatic XP balancing.
- Schema unchanged from v1.11.1: 53 tables.

---

# v1.11.1 — 🎛 Event Operations Cockpit & Reporting 2.0

- На сторінці кожної події додано **Операційний центр події**: `зареєстровані → черга/резерв → відмітка → підтверджено → XP → зворотний зв’язок` в одному робочому екрані.
- Операційний центр показує стан QR-сканера, стан часового вікна відмітки, останню дію сканера та оператора.
- Додано масові дії: оновлення черги/резервів лише для поточної події, підтвердження всіх відмічених, а після закриття check-in — масове `Не прийшов`.
- Таблиця учасників події тепер одразу показує статус, час відмітки, XP, стан зворотного зв’язку, код підтвердження та доступні дії.
- **Reporting 2.0**: кожен PDF/XLSX має точний штамп `Дані станом на DD.MM.YYYY HH:MM Europe/Kyiv`.
- KPI розділено на **потокові показники за період** і **моментні показники станом на дату**.
- Додано воронку реєстрації, воронку участі у подіях, блок якості даних та окремі визначення ключових показників.
- Додано звіт за **ISO-тиждень**. Динаміка автоматично обирає гранулярність: до 31 дня — по днях, до 120 днів — по тижнях, довший період — по місяцях.
- Для однієї точки даних лінійний графік більше не будується: PDF/XLSX показує KPI; для одного тижня/короткого періоду використовуються змістовні денні або тижневі дані.
- Посилено цілісність Reporting 2.0: майбутня подія не потрапляє у фактичні attendance KPI навіть якщо legacy-дані помилково мають статус `completed`.
- У **Журналі доступу** колонка `Хто` отримала достатню ширину і заборону розриву слів усередині імен/ролей.
- Схема БД не змінюється від v1.11.0: **53 таблиці**; оновлення сумісне з поточною production БД.

---

# v1.11.0 — 🚀 Registration UX, Feedback 2.0 & Operations Dashboard

- Registration UX: progress indicator, persistent resume/restart, inline-button answers, canonical settlement autocomplete and human-readable validation messages.
- Незавершена registration draft зберігається зашифрованою; operational funnel зберігає timestamps `start / consent / profile / submit / approved / first activity`.
- Feedback 2.0: micro-feedback в одному Telegram-потоці, одноразове reminder-повідомлення через Notification Center, per-event conversion та global response rate.
- Telegram Home отримав Next Best Action: незавершена реєстрація, pending feedback, подія сьогодні, нова відповідь у зверненні, майже виконана ціль або наступна подія. Старий блок `⚡ Швидкі дії` видалено.
- Головне меню Telegram зафіксовано у порядку `Головна / Мій профіль`, `Долучитися / Можливості`, `QR-бейдж / Запросити друга`, `Підтримати / Звернення`, `Ще`; `Адмін-панель` — окремим нижнім рядком за правами.
- Operations Dashboard: today events/attendance/no-show, upcoming check-ins, pending registrations, failed notifications, SLA requests, feedback response rate, registration funnel та data-quality issues.
- Для звернень додано `participant_last_viewed_at`, щоб Home визначав справді непрочитані відповіді команди.
- Security: secret config fields приховані з repr; Monobank errors не містять provider body/token; internal jar account id не персиститься; `/admin` відповіді отримують `Cache-Control: no-store, private`; чутливі donor fields у web бачить лише superadmin.
- Збережено v1.10.4.1 normalization для Monobank `sendId` (`jar/<id>` / `<id>` / URL).
- Додано `registration_journeys`; схема БД — **53 таблиці**.
- Додано `cryptography` для Fernet encryption registration checkpoints.

---

## v1.10.4.1 — Monobank Jar Sync Hotfix

- Виправлено зіставлення `sendId`: Monobank API повертає `jar/<id>`, тоді як публічне посилання містить `<id>`.
- Синхронізація тепер нормалізує обидва формати та коректно знаходить налаштовану банку.

# v1.10.4 — 💙 Донати, Реєстрації та UI

- Додано окремий екран **📝 Реєстрації** з KPI, схваленням/відхиленням, Telegram-сповіщенням і audit log; **👥 Учасники** містять уже схвалену базу.
- Додано Telegram-розділ **💙 Підтримати** з офіційною банкою Monobank і публічною **📄 Звітністю**.
- Додано web-модуль **💙 Донати**: стан/ціль банки, відсоток заповнення, транзакції, суми, донатери за доступними даними, динаміка по днях, перегляди сторінки підтримки, використання коштів і документи.
- Додано Monobank Personal Open API sync через секретний `MONOBANK_TOKEN`; перша виписка обмежена останніми 31 днем, подальша історія накопичується локально.
- Додано прив’язку транзакцій до профілю за АМП-кодом та вручну.
- Додано системні донатні бейджі: `Мій перший донат` ≥50 грн, `Мажор` ≥200, `Мафіозі` ≥500, `Меценат` ≥1000, `Почесний спонсор АМП` сумарно >2000, `Брюс Всемогутній` сумарно >5000 для АМПасадорської/staff ролі.
- **🌍 Можливості** отримали завантаження/відображення фото.
- Суперадміністратор бачить точні агреговані значення аналітики/звітів; інші ролі зберігають privacy suppression малих груп. Персональні списки вразливих категорій не формуються.
- Виправлено темну тему destructive-блоків, мобільний overflow карток, верстку прав доступу; редактор прав після збереження повертається закритим.
- Залишено один глобальний перемикач теми у правому верхньому куті.
- Додатково українізовано видимі англомовні підписи.
- Schema: **52 tables**; зміни additive/idempotent.
- QA у sandbox: **118/118** regression tests PASS із тимчасовими test-only compatibility shims поза релізним деревом; compile/AST/Jinja/routes/schema PASS. У production/local CI слід повторити `pytest -q` після встановлення реальних залежностей із `requirements.txt`.

---

# v1.10.3 — 🛡️ Data Integrity & Data Quality

- Додано configurable check-in/attendance window: `events.checkin_open_before_minutes=60`, `events.checkin_close_after_minutes=360`.
- User QR, Telegram/web scanner і звичайне staff attendance не допускають передчасне/прострочене зарахування.
- Web manual override вимагає причину (мін. 5 символів) і записує `web_event_attendance_override` в audit.
- Attendance confirmation залишається idempotent: повторне підтвердження не створює повторний event XP.
- Reports: completed/upcoming/in-progress events розділено; future attendance anomalies виключаються з visits/avg attendance та позначаються окремим KPI.
- `unique_participants` = реально залучені через participation actions, а не всі нові профілі.
- Report KPI розділено на period metrics і snapshot metrics.
- Додано canonical directory `settlement_references`; aliases `Анисiв`, `с.Анисів` → `Анисів`; нормалізація використовується у профілях, аналітиці, розсилках і Smart Opportunities.
- Dashboard отримав Data Quality widget і audit-дію нормалізації.
- Додано P0 regression suite `tests/test_v1103_data_integrity.py`.
- Schema: 48 tables.

---

# v1.10.2 — 🧩 Granular Permissions & Telegram Home

- Додано granular permissions для web-акаунтів і Telegram staff: participants view/edit/approve, events create/edit/delete, XP award, basic/sensitive exports, broadcasts, moderation та окремі права на основні feature-модулі.
- Додано superadmin UI для персонального ACL із reset «Права за роллю», audit та негайним оновленням дозволів active web session.
- Access control посилено на middleware/direct URL, global search, Dashboard attention та Telegram callback рівнях; malformed ACL fail-closed.
- `participants.edit` отримав окремий non-sensitive workflow; повні sensitive поля/consents/private media залишаються під жорсткішим захистом.
- `reports.sensitive_export` підключено до розширених event/donor exports.
- Зміна ролі staff скидає custom permissions, щоб stale privilege не переживав role transition.
- Telegram Home повністю оновлено: ім’я, прогрес XP, wallet, league/season, streak, години, найближча подія, quest deadline, звернення та Smart Opportunities.
- `🤝 Запросити друга` і `🆘 Звернення` винесені в основну reply-клавіатуру.
- Legacy ПІБ формату `Прізвище Ім’я` тепер коректно дає ім’я для персонального звертання.
- Schema: 47 tables; тільки additive permission columns, без нових таблиць.

# v1.10.0.1 — 🧪 Full Regression Alignment Hotfix

- Синхронізовано legacy reliability tests із канонічним Notification Center (`notifications`) v1.9+.
- Retry tests тепер перевіряють `scheduled_at`, `status`, `retry_count`, `max_attempts` канонічного notification row.
- Regression v1.8.1 для нових opportunities оновлено: з v1.9.2 немає масового `opportunity_created`; перевіряється Smart Opportunities matching та `opportunity_match`.
- Regression v1.8.2.1 waitlist оновлено під v1.10.0 Runtime Settings: 2 години = default 120 хв у `events.waitlist_reservation_minutes`, а workflow використовує `timedelta(minutes=reservation_minutes)`.
- Усі version/cache assertions тестів синхронізовано з 1.10.0.1.
- Очищено застарілий коментар у event operations: durable delivery забезпечує Notification Center.
- Runtime logic, schema БД, Telegram/Web UX та production workflows v1.10.0 не змінювалися.

# v1.10.0 — 🎨 Major UX Refresh & ⚙️ Runtime Settings

- Telegram participant UX переведено на компактне головне меню: `🏠 Головна / 🚀 Долучитися / 🌍 Можливості / 👤 Мій профіль / 🎫 QR-бейдж / ☰ Ще`; admin/coordinator бачать окрему `🛠 Адмін-панель`.
- `🚀 Долучитися` відкриває підменю Події, Квести, Волонтерство, Активності, Ідеї, Опитування.
- `👤 Мій профіль` став хабом для Профілю, XP, Ліги, Серій, Цілей, Бейджів, Винагород, Запрошень та історії сезонів.
- `☰ Ще` містить Звернення, Правила та Допомогу.
- `🏠 Головна` перетворена на «Мій АМП сьогодні»: XP до наступного рівня, ліга/сезон, streak, найближча подія, актуальний квест, звернення, нові Smart Opportunities. Активний користувач після `/start` одразу потрапляє на цей екран.
- Participant 360: усі вкладки отримали послідовні іконки — Огляд, Квести, Активності, XP, Події, Волонтерство, Ідеї, Опитування, Бейджі, Сезони, Документи.
- `⚙️ Налаштування` у web стали реальною runtime-конфігурацією без нового релізу: birthday XP, idea approved XP, referral XP, streak restore cost, freeze limit, пропуски суперсерії, threshold бейджа, event reminder, feedback delay, waitlist reservation, privacy suppression threshold та retention policy.
- Runtime rules зберігаються в існуючій `system_settings`; нових таблиць немає. Зміни журналюються, редагування — лише superadmin.
- Analytics/PDF privacy suppression threshold тепер читається з Settings; streak/event/XP automation також використовує runtime values.
- Security, Notification Center, Outcomes, Advanced Analytics, Smart Opportunities, Seasons History, Participant 360 та reliability/idempotency попередніх релізів збережені.

---

## v1.9.2 — 🌍 Smart Opportunities & 🏆 Seasons History

- `🌍 Можливості` стали персоналізованими: учасник обирає інтереси `Волонтерство / Освіта / Гранти / Обміни / Підприємництво / Культура / Спорт / IT / Медіа`.
- Smart matching враховує вік, обрані інтереси, населений пункт, формат і дедлайн. Категорії вразливості не використовуються для автоматичного profiling/matching.
- Для автоматичних рекомендацій потрібні явно обрані інтереси. Глобальний каталог можливостей при цьому залишається доступним усім учасникам.
- Додано `opportunity_matches`: система зберігає score, причини match, статус і факт сповіщення.
- Notification Center надсилає персональний digest `🌍 Для тебе знайдено ... нові можливості` з максимум 3 релевантними варіантами за один цикл та dedupe-захистом.
- Web-каталог можливостей отримав target settlements, match count, interest count та форми таргетингу за віком/напрямом/форматом/населеними пунктами.
- Сезон став історичним об’єктом: після завершення формується snapshot із TOP-3, переможцями кожної ліги, рекордами XP/streak/волонтерських годин, badge summary, league distribution та повним фінальним leaderboard.
- При створенні нового сезону попередній активний сезон фіналізується перед переключенням. Startup більше не може випадково реактивувати архівний/завершений сезон.
- У Telegram-профілі та Participant 360 додано `🕰 Історія сезонів`; web отримав окрему detail-сторінку історичного сезону.
- Схема v1.9.2: 47 таблиць. Додано additive/idempotent поля профілю/можливостей/сезонів та нову таблицю `opportunity_matches`.

## v1.9.1 — 📊 Advanced Analytics & PDF Layout Fixes

- Додано cohort funnel: зареєструвалися → прийшли 1 раз → повернулися → регулярні → АМПасадори.
- Додано retention 30/90 днів після першого підтвердженого відвідування.
- Додано внутрішній Engagement Score 0–100 (регулярність, події, волонтерство, ідеї, опитування, квести).
- Додано heatmap активності день тижня × година у web, Excel, PDF і PNG.
- KPI аналітики вирівняні в стабільну 4-колонкову сітку; виправлені некоректні переноси довгих слів/статусів.
- Notification Center: статуси більше не розбиваються по літерах у вузьких колонках.
- PDF-звіти стали багатосторінковими: KPI, великі списки подій і довгі агреговані категорії переносяться без обрізання та втрати рядків.
- Блок «Вплив» переверстано з безпечними переносами і стабільним footer.
- Excel-звіт отримав окремий аркуш `Advanced Analytics` із cohort/retention/engagement/heatmap.
# v1.9.0 — 🔔 Notification Center & Outcomes

- Додано єдиний канонічний Notification Center: нова таблиця `notifications` з одержувачем, типом, заголовком, текстом, пов’язаною сутністю, плановим/фактичним часом доставки, статусом, помилкою та retry counter.
- `queue_telegram_delivery()` тепер є backward-compatible входом у єдиний `notifications` outbox; reminder подій, перенесення/скасування, призначення відповідальних, case replies, surveys, opportunities, birthday, streak, badges, XP/reward/admin notices і manual broadcasts проходять через один durable delivery worker.
- Legacy `notification_deliveries` збережено тільки для backward compatibility; при старті всі історичні записи мігрують у `notifications` ідемпотентно, включно з рядками без старого dedupe key.
- Web отримав `🔔 Сповіщення`: KPI `В черзі / Надіслано / Помилки`, пошук, фільтри `системні / події / розсилки / кейси / streak / опитування`, status filter та кнопку `🔁 Повторити невдалі`.
- Manual broadcast campaign history збережена, але фактична Telegram-доставка виконується тим самим Notification Center worker і синхронізує статуси recipient/campaign.
- Додано post-event feedback: приблизно через 2 години після підтвердженої участі система питає оцінку 1–5, корисність, нові знання, безпеку, готовність прийти ще та необов’язковий коментар.
- Feedback має per-event analytics: середня оцінка, % корисності, нових знань, відчуття безпеки та наміру повернутися.
- Аналітика та автоматичні Excel/PDF звіти отримали outcome-метрики. PDF має окрему сторінку `Вплив` із формулюваннями для сільради, донорів і грантової звітності.
- Додано таблицю `event_feedback`; metadata v1.9.0 = 46 таблиць.
- Security/reliability бази v1.7.3–v1.8.2.5 збережені: role access, protected media, CSRF/2FA, idempotent XP, distributed locks, Telegram retries, waitlist/attendance, Participant 360, lifecycle і continuous Telegram QR scanner.

# v1.8.2.5 — 🔔 Version Dedupe & Compact Telegram Admin Menu

- Автоматичне повідомлення про нову версію переведено з legacy BroadcastCampaign на durable notification outbox із UNIQUE per-user/per-version dedupe key.
- Додано завершення незакінчених legacy `system_update` campaigns до startup recovery, щоб старий version broadcast не відновлювався після deploy.
- `queue_telegram_delivery` отримав race-safe dedupe через nested transaction + unique constraint; DB `job_lock` більше не допускає паралельний re-entry тим самим worker.
- Telegram admin-панель стала дворівневою: перший екран показує лише `Події / Активності / XP та винагороди / Учасники / Аналітика й комунікація / Вебпанель`, а конкретні дії відкриваються у підменю.
- Role-based права coordinator/admin/superadmin збережені; у кожному підменю є `⬅️ Головне меню`.
- БД без schema changes: 44 таблиці. Targeted regression v1.8.1–v1.8.2.5: 33 PASS.

# v1.8.2.3 — 📷 Telegram QR Scanner & Runtime Fixes

## v1.8.2.4 — Continuous Telegram Scanner & Version Notification Fix

- `📷 QR Scanner` у Telegram тепер запускає Mini App з native `showScanQrPopup`; event-button відкриває scanner напряму.
- Камера відкривається автоматично та залишається відкритою після кожного QR для послідовного сканування бейджів.
- Кожен scan надсилає адміністратору в чат підтвердження: ПІБ, AMP-ID, подія, реєстрація та attendance.
- Для незареєстрованого учасника в чаті приходить `✅ Зареєструвати та підтвердити`.
- Scan API автентифікує staff через підписаний Telegram Mini App `initData`; web admin cookie для цього не використовується.
- Старий текстовий scanner з AMP-ID збережено як fallback.
- Автоматичне повідомлення про нову `APP_VERSION` захищене distributed DB lease, щоб два startup-процеси не створювали два однакові broadcast campaign.
- Схема БД без змін.


- Додано `📷 QR Scanner` у Telegram admin-панель для coordinator/admin/superadmin. Після вибору активної події scanner state зберігається в FSM, а персональний `profile_...` QR учасника в цьому режимі працює як attendance scan.
- Якщо учасник уже registered/reserved/checked_in — scanner виконує idempotent attendance confirmation і нарахування. Якщо не зареєстрований — з'являється `Зареєструвати та підтвердити`.
- Scanner приймає також AMP-ID або текст/посилання персонального QR. На web додано cross-browser endpoint, який відкриває відповідний Telegram scanner deep-link; native `BarcodeDetector` лишається додатковим fallback.
- Виправлено runtime падіння `📆 Календар`: у Jinja `day.items` конфліктував із методом Python dict `items`; модель дня тепер передає `entries`, а template використовує `day.entries`.
- Виправлено runtime падіння `💡 Ідеї` та `🆘 Звернення`: відсутні `IDEA_STATUSES`, `REQUEST_STATUSES`, `REQUEST_CATEGORIES`, `REQUEST_PRIORITIES` додані до `ui_labels.py` та імпортуються явно.
- Прибрано випадковий дубль scanner JavaScript із title-block `event_detail.html`.
- База даних без змін: 44 таблиці; нових schema migrations немає.
- Regression: 24 targeted tests PASS; compileall/AST/Jinja PASS; 162 unique FastAPI method+path routes, duplicates 0.

# v1.8.2.2 — 🩹 FastAPI/Pydantic startup hotfix

- Виправлено критичний startup crash після v1.8.2.1 у web QR Scanner.
- Причина: FastAPI/Pydantic v2 не дозволяє body/form-параметри з Python-іменами, що починаються з `_`; параметр `_csrf: Form(...)` створював Pydantic field `_csrf` під час реєстрації route і валив імпорт застосунку.
- `_csrf` прибрано із сигнатури scanner route. Захист CSRF НЕ послаблено: `CSRFMiddleware` як і раніше перевіряє hidden/form field `_csrf` для всіх unsafe `/admin` POST/PUT/PATCH/DELETE до входу в route.
- Calendar, QR Scanner, waitlist, attendance workflow та вся логіка v1.8.2.1 збережені без змін.
- Додано regression guard, який перевіряє, що FastAPI Form/File/Body параметри route не мають Python-імен із leading underscore.

# v1.8.2.1 — 📅 Calendar & Event Operations

- Єдиний web-календар переведено на режими `День / Тиждень / Місяць`; у ньому разом показуються події, квести, волонтерські задачі, опитування, дедлайни можливостей, кейсів, ідей/мініпроєктів та streak freezes. Для кожного типу використовується іконка плюс окремий accent.
- На detail-сторінці події додано browser QR Scanner: `📷 Почати check-in` відкриває камеру телефона, `BarcodeDetector` читає персональний QR/AMP-ID; є ручний fallback для браузерів без QR API.
- Зареєстрований учасник після scan проходить check-in + idempotent attendance confirmation; незареєстрованого можна одним підтвердженням `Зареєструвати та підтвердити`.
- Додано waitlist для capacity-подій: коли місць немає, Telegram пропонує `⏳ Стати в чергу`. Після звільнення місця найстаріший waitlisted participant отримує 2-годинний `reserved` слот і durable Telegram notification.
- Прострочений резерв автоматично повертається в чергу; scheduler/web lifecycle просуває наступного учасника.
- Attendance workflow уніфіковано статусами `registered / cancelled / waitlisted / reserved / checked_in / attended / no_show`; після завершення події непідтверджені registered/reserved автоматично стають no-show.
- До `event_registrations` additive/idempotent додано `waitlisted_at`, `waitlist_promoted_at`, `reservation_expires_at`, `no_show_at` та індекси для waitlist/reservation. Нових таблиць немає — metadata = 44.
- `Permissions-Policy` дозволяє camera лише `self`; microphone/geolocation лишаються забороненими.
- QA: targeted v1.8.1 + v1.8.2 + v1.8.2.1 = 16 tests PASS; compile/AST/Jinja PASS; 161 unique FastAPI method+path routes, duplicates 0.

# v1.8.2 — 🎨 Participant 360 UI Polish

- У Participant 360 `🎯 Квести` та `⚡ Активності` розділено на дві окремі вкладки замість одного двоколонкового блоку, який міг накладатися на вузькій робочій області.
- KPI Participant 360 виправлено на справжню сітку **4 картки в ряд** на desktop: 8 показників відображаються як 4×2, із компактнішим шрифтом, однаковою висотою, центруванням і стабільними відступами.
- Текст у вкладках і таблицях Participant 360 вирівняно та відцентровано; довгі назви безпечно переносяться всередині своєї колонки, статус і дата не злипаються та не накладаються.
- Вкладки Participant 360 уніфіковано за шириною/висотою; на мобільних вони прокручуються горизонтально без ламання макета.
- Прибрано дубль таблиці `Останні операції з досвідом` унизу картки учасника: історія XP залишається в окремій вкладці `XP`, а ручне нарахування XP залишається доступним у блоці керування.
- Оновлено cache-buster `admin.css` до `v1.8.2`, щоб браузер після deploy не залишав старі стилі Participant 360.
- База даних і маршрути не змінюються: **44 таблиці**, **159 унікальних FastAPI method+path**, 0 дублікатів.

# v1.8.1 — 👤 Participant 360 & Lifecycle

- Новий Participant 360 у картці учасника: top summary, 8 KPI, unified timeline та вкладки Огляд / Активність / XP / Події / Волонтерство / Ідеї / Опитування / Бейджі / Документи.
- Нові автоматичні статуси профілю `deleted` («Видалено») і `deleted_permanent` («Видалено без можливості відновлення»). Дані, XP та історія не видаляються фізично. Ці статуси не можна встановити вручну.
- 60 днів без активності: профіль participant/ambassador автоматично переходить у `deleted`; попередження надсилаються на 55-й і 59-й день. Blocked та staff-ролі не обробляються.
- `/start` для `deleted` показує можливість відновлення; коротка Telegram-форма збирає причину повернення й плани активності. Superadmin розглядає запит у Participant 360.
- Після схвалення відновлення діє 14-денний випробувальний строк. Підтверджена участь знімає probation автоматично; без участі профіль переходить у `deleted_permanent` без права повторного відновлення.
- `TelegramForbiddenError` для participant/ambassador також переводить профіль у `deleted`, зберігаючи 30-денний referral clawback.
- Нова подія, квест, волонтерська задача, активність, опитування або можливість автоматично повідомляє всіх активних учасників через надійні існуючі broadcast/outbox механізми.
- Аналітика розширена lifecycle та participation-mix метриками, а звіти — показниками активних/неактивних/видалених профілів, запитів на відновлення, probation, дій участі та середнього XP на залученого.
- Web-назва `Health` у UI уніфікована як `🩺 Стан системи`.
- Схема залишається 44 таблиці; нові поля `users` додаються additive/idempotent release-міграцією. Static QA: 159 унікальних FastAPI method+path routes без дублікатів, 45 Jinja templates, 73 Python files; v1.8.1 feature tests 6 PASS.

# v1.8.0 — 🔔 Admin UX

- Єдиний breadcrumb/page spacing/action-control standard для web-панелі.
- Dashboard Attention Center із direct filtered links.
- Global Search + grouped results.
- Grouped sidebar + Calendar + Settings.
- Smart filters на основних списках із session persistence.
- Telegram FSM navigation confirmation: reply-menu button text не потрапляє у форму; Yes/No збереження/скасування state.
- 60-day inactivity soft-removal: warning 5d/1d, inactive on day 60, ban/staff exclusion, durable notifications, referral clawback compatibility.
- System Health standardized actions + manual retry failed Telegram outbox.
- Схема БД без нових таблиць: 44; 157 static FastAPI method+path routes; 45 Jinja templates.

# v1.7.4.1 — Events Sharing, Donor Registers & Referral Guard

- Web події: публічна картка на окремому `share_token`, кнопки «Поділитися / Копіювати / Відкрити», без розкриття check-in token.
- Telegram: пересилання події другу; admin/superadmin отримують пряме registration deep-link; coordinator/admin/superadmin можуть обрати активну подію й завантажити PNG QR check-in.
- Події: завантаження donor templates `.docx` / `.xlsx` і формування заповненого реєстраційного списку зі збереженням існуючої структури/стилів, наскільки це дозволяє шаблон. За відсутності шаблону — стандартний AMP XLSX.
- Attendance: після підтвердження участі генерується унікальний SHA-256 confirmation code; він потрапляє у web-таблицю та реєстраційні експорти. Код є внутрішнім технічним підтвердженням, не КЕП.
- Referrals: якщо invited user стає inactive протягом 30 днів після referral reward, рівно отриманий referral XP сторнується idempotently; inviter отримує durable notification. `TelegramForbiddenError` у outbox/broadcast позначає participant/ambassador inactive.
- Rewards: додано 9 сервісних винагород (5/15/45/50/50/75/100/100/150 XP); тип `service` дозволяє повторне замовлення після виконання попередньої заявки.
- Ideas UX: обрана категорія фіксується inline як `✅` вибір.
- Схема залишається 44 таблиці; additive columns для events/event_registrations/referrals.
- Tests: 18 PASS.

# v1.7.4 — Reliability & Architecture

- Додано повноцінний `tests/` з автоматичними тестами критичних workflow: реєстрація, подія, квест, волонтерська задача, активність, опитування, ідея → мініпроєкт, кейс, streak/freeze/restore, broadcast retry, scheduler lock та повторний запуск міграції.
- Критичні операції схвалення квестів/волонтерства, завершення опитування та +10 XP за схвалення ідеї винесено в тестовані idempotent workflow-функції, щоб повторний запит не дублював XP/години.
- Великий `app/web/app.py` фізично розділено: feature routes винесено в `app/web/routes/` (`dashboard`, `users`, `events`, `quests`, `tasks`, `activities`, `ideas`, `requests`, `surveys`, `analytics`, `reports`, `broadcasts`, `gamification`, `opportunities`, `system`).
- Додано таблицю `scheduled_jobs` і distributed DB-lease. Birthday XP, event reminders, lifecycle, streak, goals, Telegram retry та broadcast retry не виконуються паралельно двома процесами.
- Додано durable Telegram outbox `notification_deliveries`: системне повідомлення спочатку записується в БД, а при тимчасовій помилці Telegram повторюється через 1 / 5 / 15 хв; після першої спроби та трьох невдалих повторів має статус `failed`.
- Розсилки також отримали `attempt_count`, `last_attempt_at`, `next_retry_at` та до трьох повторних спроб після першої невдалої доставки. Кампанія не вважається завершеною, поки є одержувачі у `pending/retry`.
- Додано web-розділ `🩺 Стан системи`: Bot, Database, Scheduler, APP_VERSION/Heroku release, pending/failed Telegram deliveries, broadcast errors, pending jobs, media storage, останній successful job і доступна інформація про backup.
- Схема БД зростає з 42 до 44 таблиць: `scheduled_jobs`, `notification_deliveries`; міграція additive/idempotent, повторний SQLite → PostgreSQL перенос не потрібен.

# v1.7.3 — Stability & Security

- Приватні медіафайли розділено на public / participant-private / staff-private / superadmin-private; невідомі категорії закриті за замовчуванням. `/media`, legacy `/uploads` і `/private` перевіряють сесію/роль, а перегляд sensitive media записується в аудит.
- Web-акаунти перенесено в БД: пароль зберігається лише як PBKDF2-SHA256 hash; legacy `WEB_ADMIN_PASSWORD` / `WEB_STAFF_ACCOUNTS_JSON` використовуються тільки для одноразового bootstrap і після перевірки входу можуть бути видалені з Heroku Config Vars.
- Додано політику сильних паролів, примусову зміну тимчасового пароля, reset суперадміном, 5 невдалих спроб → 15 хв блокування.
- Для superadmin 2FA обов’язкова через одноразовий Telegram-код; для admin її можна увімкнути в `🔐 Мій доступ`.
- Додано серверні web-сесії з історією пристрою/часу, завершенням окремої сесії та `Завершити всі сесії` суперадміном.
- Усі unsafe `/admin` POST/PUT/PATCH/DELETE захищено CSRF token; cookie переведено на SameSite=Strict, додано security headers.
- Аудит розширено: login/logout/failed login/2FA, reset/change password, sensitive media, sensitive exports, XP, ролі, бейджі, серії, consent та критичні видалення.
- Privacy threshold: категорії вразливості 1–4 не показуються буквально — у таблицях `<5`, у графіках точне значення не передається.
- Додано сторінки `🔐 Мій доступ` та `🛡 Безпека доступу`.
- Схема БД: нові таблиці `web_staff_accounts`, `web_admin_sessions`; міграція additive/idempotent.

# v1.7.2 — leagues ×6, self-freeze streaks, compact streak admin, surveys UX and branded exports

- Додано Telegram-блок `🔥 Серії участі`: власна тижнева серія, суперсерія, рекорди, пропуски, квартальна квота заморозки та самостійна заморозка на N днів (до 14 днів сумарно за календарний квартал).
- Web `🏆 Рейтинг і серії`: таблиця серій стала компактною; редагування винесене на окрему сторінку учасника з KPI, ручною корекцією, заморозкою на запит учасника, історією заморозок і перерахунком з історії.
- Ліг тепер 6: Бронзова, Срібна, Золота, Платинова, Діамантова 1000–1499 XP і Легендарна 1500+ XP. ТОП-10 кожної ліги вирівняний у сітку 3×2, ПІБ та XP — в одному рядку.
- У Telegram на кнопках каталогу активностей одразу показується XP.
- Опитування: спрощений web-конструктор варіантів; multiple-choice у Telegram перемикає варіанти в тому самому повідомленні і завершується кнопкою `✅ Готово`.
- Розсилки: аудиторія `Усі учасники зі статусом «Активний»` підписана явно.
- Розширено способи вимірювання цілей і автоматичних бейджів: задачі, опитування, активності, реалізовані ідеї, бейджі, запрошення та серії.
- Нового учасника можна підтвердити у web: суперадмін активує одразу, звичайний admin створює захищений запит на підтвердження.
- Список учасників події отримав брендовані PDF-експорти (базовий та розширений для суперадміна); Excel отримав друковані header/footer і брендоване оформлення.
- Автоматичні PDF/Excel-звіти додатково відполіровані у стилі АМП.
- Схема БД у v1.7.2 не змінюється від v1.7.1.

# v1.7.1 — survey exports, streak freeze, analytics/reporting and web polish

- Уніфіковано breadcrumbs («шлях») та max-width/відступи сторінок web-панелі; виправлено KPI-картки `Рейтинг і серії`, щоб число, підпис та пояснення не злипалися.
- У `📋 Опитування` додано загальний Excel та PDF, PNG для результату кожного питання, сторінку відповідей конкретного респондента та фото до питання з додаванням/заміною/видаленням.
- Фото питання відображається учаснику в Telegram перед варіантами/полем відповіді.
- Додано `streak_freezes`: ручна заморозка серії на N днів із сумарним лімітом 14 днів на календарний квартал. Активна заморозка захищає тижневу серію та суперсерію від пропусків.
- У `🏆 Рейтинг і серії` показується активна заморозка, використано/залишилось днів квартального ліміту; заморозка створюється з приміткою й записується в аудит.
- `📊 Аналітика` доповнена проходженнями опитувань по тижнях, бейджами по тижнях, розподілом учасників по лігах і станом серій/заморозок. Excel/PDF/PNG працюють і для цих нових метрик.
- `📄 Звіти` доповнені отриманими бейджами, днями заморозки, поточним зрізом ліг та серій; Excel має аркуші `Гейміфікація` і `Бейджі по тижнях`, PDF — окремі сторінки.
- У БД додано таблицю `streak_freezes` і поле `survey_questions.image_path`; міграція additive/idempotent, повторний перенос SQLite → PostgreSQL не потрібен.

# v1.7.0 — ліги, рейтинги, серії участі та відповідальні

- Якщо учасника призначено відповідальним за ідею або звернення, він автоматично отримує Telegram-повідомлення з кнопкою `👁 Детально`; доступ до деталей перевіряється за профілем/роллю.
- Рейтинг у Telegram поділено на дві кнопки: `🌍 Загальний рейтинг · ТОП-20` та `🏆 Рейтинг моєї ліги`; у своїй лізі учасник бачить власне місце і ТОП-10.
- Додано 5 сезонних ліг за XP: Бронзова 0–99, Срібна 100–249, Золота 250–499, Платинова 500–999, Діамантова 1000+.
- У web додано окремий розділ `🏆 Рейтинг і серії`: загальний ТОП-20, ТОП-10 кожної ліги, кількість учасників по лігах та аналітика серій.
- Додано тижневу серію активності: послідовні календарні тижні з підтвердженою XP-активністю (події, квести, активності, задачі, опитування, ідеї, реферали). Поточний тиждень не обриває серію, доки ще триває.
- Додано суперсерію відвідування подій: дозволено пропустити 1 подію поспіль і максимум 2 події за поточну серію; другий поспіль або третій загальний пропуск обриває серію.
- За суперсерію тривалістю 30+ днів автоматично видається бейдж `🔥 Суперсерія 30 днів`.
- Втрачена суперсерія зберігається як доступна для відновлення. Додано спеціальний тип винагороди `streak_restore`; стартова винагорода `Повернути суперсерію` коштує 100 XP і може бути відредагована у web.
- У web-блоці серій адміністратор може коригувати показники, додавати примітку або повністю перерахувати серію з історії. Ручна корекція ставиться на `🔒` і не перезаписується автоматичним scheduler до ручного перерахунку.
- Профіль учасника у Telegram та web показує лігу, тижневу серію і суперсерію.
- Додано таблицю `participation_streaks` та поле `rewards.reward_type`; міграція additive/idempotent, повторний перенос SQLite → PostgreSQL не потрібен.

# v1.6.9 — polls, event lifecycle, admin approvals and web UI polish

- Виправлено відображення карток ідей на широких екранах і в темній темі; контент та кнопки більше не «роз'їжджаються».
- Виправлено темну тему розділу `📄 Звіти`: блок «Що включається автоматично» використовує системні кольори теми, текст читабельний.
- Уніфіковано відступи, ширину й вирівнювання в `Зверненнях`, `Розсилках`, `Модерації` та `Бейджах`.
- Додано web-модуль `📋 Опитування`: створення опитування, питання одного/декількох варіантів або текстові, дедлайн, XP, публікація, закриття, агреговані результати й список проходжень.
- Після публікації опитування активні учасники автоматично отримують Telegram-повідомлення; у боті з'явився розділ `📋 Опитування`, а XP нараховується один раз після повного проходження.
- Прострочені опитування автоматично закриваються lifecycle-процесом.
- У звіти АМП додано кількість опублікованих опитувань і проходжень.
- Статуси подій уніфіковано: `Чернетка`, `Відкрита реєстрація`, `Реєстрацію закрито`, `Перенесено`, `Завершено`, `Скасовано`; закриті для нової реєстрації події залишаються видимими у Telegram, а вже зареєстрований учасник може скасувати свою участь.
- `🤝 Запросити друга` отримав кнопку генерації персонального PNG QR-запрошення.
- Зміна статусу учасника звичайним web-адміністратором тепер створює запит; фактичну зміну підтверджує або відхиляє суперадміністратор. У списку учасників суперадмін бачить чергу таких запитів.
- Додано `scripts/promote_existing_user.py` для зміни ролі вже існуючого профілю без створення дубля; його можна використати для Вови Дороша, а окремий web-login створюється через `scripts/add_staff_account.py`.
- Нові таблиці: `surveys`, `survey_questions`, `survey_responses`, `user_status_change_requests`. Міграція additive: повторний SQLite → PostgreSQL перенос не потрібен.

# v1.6.8 — evidence, badges, reminders, missions and consents

- Фото/скріншоти як підтвердження виконання активностей у Telegram і web.
- Web-видача бейджів одному або одразу кільком учасникам; окремі загальні та АМПасадорські бейджі, PNG для АМПасадорських.
- Автоматичне нагадування учасникам події за 1 годину до початку.
- +10 XP автору за перше схвалення ідеї.
- Кнопки «⬅️ Назад» у переглядах Telegram без втручання у форми введення.
- Перероблені цілі/місії: завдання, метрика, дедлайн, XP-нагорода, опис і фото.
- Документи та згоди: згода батьків, файл/скан, дата; версія/дата фото-відеозгоди та історія змін.
- Кольорове позначення етапів ідей.

# AMP XP v1.6.7

## Telegram UX: повні назви та охайні списки
- Учасницькі кнопки подій, квестів, активностей, волонтерських задач і можливостей більше не обрізають назви на 28 символах.
- Для цих розділів кнопки залишено по одній у рядку, а повні назви додатково показуються в текстовому списку над клавіатурою — навіть якщо конкретний Telegram-клієнт візуально стискає кнопку.
- Прибрано зайві метадані з текстів кнопок (дата, лічильники місць, XP), щоб назві залишалося максимум простору; дата, XP, місця й статус показуються в самому повідомленні.
- Уніфіковано відступи та структуру повідомлень: заголовок → коротка підказка/легенда → повний список → кнопки.

## QR-бейдж
- Видима назва в головному меню — тільки `🎫 Мій QR-бейдж`.
- Старі підписи `Мій QR-код` / `Мій QR` залишені лише як прихована сумісність для старих клавіатур Telegram. Якщо користувач натискає стару кнопку, бот одразу оновлює головне меню та показує нову назву.

## Сумісність
- Структура БД не змінюється; міграція не потрібна.
- `VERSION.txt` та `APP_VERSION` синхронізовано на `1.6.7`.

---

# AMP XP v1.6.6

## Життєвий цикл квестів і задач
- Квести після проходження дедлайну автоматично переходять у статус `Завершено` так само, як події та волонтерські задачі.
- Застарілі кнопки участі/виконання після дедлайну додатково блокуються серверною перевіркою.
- Вирівняно та стабілізовано блоки перенесення, скасування і видалення волонтерських задач у web на широких і мобільних екранах.

## Telegram UX
- Скорочено й уніфіковано тексти кнопок; довгі динамічні назви автоматично скорочуються без `...` або `…` у кінці.
- Перевірено головне меню, списки подій, квестів, задач, винагород, можливостей і адмін-меню.

## Персональний QR-бейдж
- Розділ перейменовано з «QR-код» на `QR-бейдж`.
- Після відкриття доступне окреме меню: згенерувати бейдж, додати/замінити фото, завантажити PNG, поділитися, прибрати фото.
- Фото приймається через Telegram до 20 МБ і зберігається для наступних генерацій.
- PNG-бейдж має фіксований друкарський розмір 55×85 мм при 300 DPI, оновлений центрований дизайн, логотип, ПІБ, ID АМП, рівень, XP, години та QR.
- Завантаження надсилає PNG як файл; «Поділитися» надсилає готовий бейдж і кнопку для поширення публічного посилання.

## Ідеї → міні-проєкти
- Після статусу `Схвалена` відкривається повноцінний блок реалізації: відповідальний, команда, дедлайн, бюджет/ресурси, завдання, прогрес 0–100%, результат і фото.
- Додано візуальний шлях `Ідея → Схвалення → Реалізація → Результат`.
- Зберігаються дати схвалення, початку реалізації та завершення.

## Звернення → кейси
- Звернення отримують номер формату `AMP-РІК-XXXX`, категорію, пріоритет, відповідального та дедлайн відповіді.
- Статуси: `Нове → В роботі → Очікує відповіді → Вирішено → Закрито`.
- Додано історію переписки учасника з командою АМП та фото-вкладення до 20 МБ.
- Учасник бачить свої кейси у Telegram, може відкрити історію та відповісти текстом або фото.
- При зміні публічних параметрів/статусу та відповіді команди учасник отримує Telegram-повідомлення.

## Дані та сумісність
- Додано поля міні-проєкту до `ideas`, розширені поля кейсів у `request_cases` та таблицю `request_messages`.
- Міграція виконується ідемпотентно через стандартну release-ініціалізацію; повторний перенос SQLite → PostgreSQL не потрібен.

---

# AMP XP v1.6.5

## Навігація Telegram та стабільність форм
- Виправлено системний FSM-баг: кнопки головного меню та базові команди більше не зараховуються як текстова відповідь у незавершених майстрах ідей, звернень та інших покрокових форм.
- Натискання пункту головного меню скидає незавершений сценарій і одразу відкриває обраний розділ.

## Учасники
- Додано ручний статус `Неактивний`. Профіль, XP, години та історія участі не видаляються; адміністратор може повернути учасника до активного статусу.

## Життєвий цикл подій, квестів і волонтерських задач
- Учасник може самостійно скасувати свою реєстрацію/участь у Telegram; адміністратор може зробити це у web без видалення історії.
- Додано статус `Перенесено`: обов'язкова причина + нова дата/час + автоматичне Telegram-повідомлення всім залученим учасникам.
- Після завершення дати/дедлайну сутності автоматично переходять у статус `Завершено` і більше не показуються у списках актуальних активностей учасника.
- Фоновий lifecycle-процес перевіряє прострочений контент кожні 5 хвилин; помилки фіксуються в логах.

## Автоматичні звіти АМП
- Новий web-розділ `📄 Звіти` з формуванням звіту за місяць, діапазон місяців, квартал або рік.
- Формати: Excel та брендований PDF.
- У звіті: події, унікальні залучені учасники, відвідування, середня відвідуваність, волонтерські години, задачі, квести, активності, ідеї, звернення, нові учасники, XP, інтерес до можливостей, вікова/гендерна/територіальна статистика.
- Категорії вразливості формуються тільки агреговано без ПІБ, контактів і списків конкретних осіб.

## Жива гейміфікація
- Додано streak активних місяців.
- У Telegram показується прогрес до наступного рівня у форматі `поточний XP / поріг XP` та скільки XP залишилось.
- Новий блок `🏁 Цілі & місії`: сезонні, персональні та командні цілі з автоматичним розрахунком прогресу за XP, відвідуваннями, годинами, квестами, активностями або реалізованими ідеями.

## Каталог можливостей
- Додано повноцінний web-розділ `🌍 Можливості` для грантів, навчання, обмінів, стажувань, конкурсів і волонтерства.
- Поля: тип, напрям, формат, вікові межі, дедлайн, посилання, опис та активність.
- У Telegram учасник може позначити `💙 Мені цікаво` / `Більше не цікаво`; web показує агреговану кількість зацікавлених.
- Прострочені можливості автоматично перестають показуватися як активні.

## Аналітика
- До загального dashboard та кожного окремого графіка додано експорт у PNG.
- Збережено Excel/PDF-експорти та агрегований захист категорій вразливості.

## Дані та сумісність
- Додано таблиці `goals` та `opportunity_interests`.
- Додано поля перенесення до подій/квестів/задач, статус квесту та розширені поля можливостей.
- Release-ініціалізація БД виконує ідемпотентне оновлення існуючої PostgreSQL/SQLite-схеми; повторний перенос SQLite → PostgreSQL не потрібен.

---

# AMP XP v1.6.4

## Автоматизована аналітика
- Додано окремий web-dashboard `📊 Аналітика` з live-розрахунком показників із production-бази.
- Нові учасники за 12 місяців, активні 30/90 днів, підтверджені відвідування та середня відвідуваність подій.
- Волонтерські години за джерелами, розподіл за віком, статтю та населеним пунктом.
- Джерела XP, статуси ідей та кількість реалізованих ідей.
- Категорії вразливості показуються тільки агреговано, без ПІБ і контактів.
- Кожен графік має окрему детальну сторінку, Excel і PDF.
- Додано загальний Excel із окремими аркушами та Excel-графіками, а також загальний багатосторінковий PDF.
- Додано спрощене зведення аналітики у Telegram-адмінці з кнопкою переходу до web-dashboard.
- UI карток, KPI, таблиць та кнопок адаптовано до загального дизайну web-простору.

---

# AMP XP v1.6.3

## Нове

- Додано безпечне скасування подій, квестів і волонтерських задач із обов’язковою причиною та автоматичною Telegram-розсилкою всім залученим учасникам.
- Додано остаточне видалення цих сутностей лише для суперадміністратора. Перед видаленням аудиторія повідомлення зберігається в БД; уже нарахований XP/години не анулюються.
- Для скасованих сутностей зберігаються причина та час скасування; їх не можна випадково повторно активувати звичайним редагуванням.
- Додано автоматичне повідомлення всім зареєстрованим учасникам при зміні версії застосунку. Повторний рестарт тієї самої версії не дублює повідомлення.
- У «📣 Розсилки» додано власні шаблони: створення, редагування, увімкнення/вимкнення та видалення.
- Додано helper `scripts/add_staff_account.py`, який безпечно додає іменний web-admin акаунт у Heroku без стирання вже наявних staff-акаунтів.
- Оновлено responsive UI для блоків скасування/видалення та керування шаблонами.

---

# AMP XP v1.6.2

## Комунікаційний центр
- Новий розділ web `📣 Розсилки`, доступний лише суперадміністратору.
- Фільтри: всі активні, АМПасадори, вік, населений пункт, конкретна подія, неактивність N днів.
- Шаблони: нагадування про подію, привітання, новий квест, нова можливість.
- Попередній перегляд перед запуском.
- Персоналізація через `{first_name}` / `{full_name}`.
- Фонове надсилання через Telegram із помірним rate limit.
- Історія кампаній і статус доставки кожному одержувачу.
- Автовідновлення незавершених кампаній після перезапуску Heroku.
- Telegram-кнопка `📣 Розсилки` тепер веде до web-комунікаційного центру і доступна лише суперадміну.

## Дані та сумісність
- Додані таблиці `broadcast_campaigns`, `broadcast_recipients`.
- Додане поле `users.last_activity_at` та індекс.
- Існуючі PostgreSQL-дані не потрібно переносити повторно: `release` сам створить нові таблиці/поле.

## Інше
- CSS/asset cache version: `1.6.2`.
- Health endpoint: `1.6.2`.
