# AMP XP / «АМПасадори» v1.8.2.5
## 🔔 Version dedupe + compact Telegram admin panel

### Що виправлено

#### 1. Повідомлення про оновлення більше не повинно дублюватися
У v1.8.2.4 одного distributed lock виявилося недостатньо для всіх сценаріїв startup/recovery. У v1.8.2.5 механіка змінена на три рівні idempotency:

1. `job_lock(version_announce:{APP_VERSION})` — лише один startup-процес готує розсилку;
2. `system_settings.last_announced_app_version` — повторний restart тієї самої версії не запускає нове повідомлення;
3. кожному учаснику повідомлення ставиться в `notification_deliveries` з UNIQUE ключем
   `system_version_update:{APP_VERSION}:user:{user_id}`.

Тобто навіть якщо два процеси одночасно спробують поставити однакове повідомлення, база даних дозволить існувати лише одному outbox-запису для конкретної версії та конкретного учасника.

Додатково перед recovery автоматично завершуються незакінчені legacy `BroadcastCampaign` з `template_code=system_update`, щоб старий queued/sending version broadcast не відновився після deploy і не дав друге повідомлення.

Також `queue_telegram_delivery()` тепер race-safe через nested transaction + UNIQUE `dedupe_key`, а distributed `job_lock` більше не дозволяє повторне паралельне захоплення того самого lock навіть тим самим worker/process.

#### 2. Telegram адмін-панель стала дворівневою
Замість довгого списку з 20+ кнопок перший екран містить лише основні розділи:

- `📅 Події`
- `🎯 Активності`
- `🏆 XP та винагороди`
- `👥 Учасники` — admin/superadmin
- `📊 Аналітика й комунікація` — admin/superadmin
- `🌐 Вебпанель`

Після натискання відкриваються підпункти.

**Події:** створити подію, відвідування, QR Scanner, QR відмітки, посилання на подію.

**Активності:** створити/перевірити квести, заявки активностей, створити/перевірити волонтерські задачі, додати можливість.

**XP та винагороди:** нарахувати XP, видати бейдж, додати винагороду, заявки винагород.

**Учасники:** нові учасники; для superadmin — модерація.

**Аналітика й комунікація:** аналітика, Excel-експорт; для superadmin — розсилки.

У кожному підменю є `⬅️ Головне меню`. Role-based права не змінені.

### База даних
Нових таблиць і колонок немає. Metadata = 44 таблиці.

### QA
- targeted regression v1.8.1–v1.8.2.5: **33 PASS**;
- нові v1.8.2.5 tests: **5 PASS**;
- `compileall`: PASS;
- AST: 80 Python files / 0 errors;
- Jinja: 46 templates / 0 errors;
- FastAPI routes: 164 / unique 164 / duplicates 0;
- SQLAlchemy tables: 44;
- leading-underscore FastAPI risk params: 0.

Повний historical `pytest -q` у поточному sandbox не збирається через відсутній runtime package `aiogram`; це обмеження середовища, а не заявлений PASS повного suite.
