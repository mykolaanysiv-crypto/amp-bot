# АМП XP / «АМПасадори» v1.10.0 — 🎨 Major UX Refresh & ⚙️ Runtime Settings

## Що змінилося

### Telegram — нова навігація
- Головна клавіатура: `🏠 Головна`, `🚀 Долучитися`, `🌍 Можливості`, `👤 Мій профіль`, `🎫 QR-бейдж`, `☰ Ще`.
- Для coordinator/admin/superadmin окремо показується `🛠 Адмін-панель`; права не розширювалися.
- `🚀 Долучитися`: Події / Квести / Волонтерство / Активності / Ідеї / Опитування.
- `👤 Мій профіль`: Профіль / XP / Ліга / Серії / Цілі / Бейджі / Винагороди / Запрошення / Історія сезонів / Інтереси.
- `☰ Ще`: Звернення / Правила / Допомога.
- Старі reply-labels залишені як compatibility aliases, тому кешована клавіатура Telegram та FSM navigation не ламаються.

### 🏠 Мій АМП сьогодні
Активний учасник після `/start`, `/menu` або `🏠 Головна` отримує короткий персональний dashboard: XP і залишок до рівня, season/league, streak, найближча відкрита подія, найближчий власний quest deadline, звернення, що очікують відповіді, і нові Smart Opportunities.

### Participant 360
Усі вкладки отримали іконки: `🏠 Огляд / 🎯 Квести / ⚡ Активності / ⚡ XP / 📅 Події / ✅ Волонтерство / 💡 Ідеї / 📋 Опитування / 🏅 Бейджі / 🏆 Сезони / 📄 Документи`.

### ⚙️ Runtime Settings
Web `Система → ⚙️ Налаштування` тепер керує правилами через `system_settings`:
- XP: birthday, approved idea, referral maximum, streak restore cost;
- Streak: freeze limit/quarter, total + consecutive misses, badge threshold days;
- Events: reminder lead minutes, feedback delay, waitlist reservation minutes;
- Privacy: suppression threshold і retention policy value.

Редагування доступне лише superadmin; кожне збереження йде в audit. Analytics і reports більше не мають жорсткого `<5`: suppression threshold береться з runtime Settings. Існуючий lifecycle deleted/restoration не переводиться на destructive physical delete — історія та audit зберігаються відповідно до чинної моделі.

## База даних
- Таблиць: **47**.
- Нових таблиць/полів немає. Runtime-конфігурація зберігається в існуючій `system_settings`.
- Release-init ідемпотентно додає default keys, тому повторний перенос SQLite → PostgreSQL не потрібний.

## Встановлення
1. Зробіть Heroku PostgreSQL backup.
2. Розпакуйте `amp_bot_v1100.zip`.
3. Скопіюйте код у production working tree через `rsync`, не перезаписуючи `.git/.env/.venv/data`.
4. Перевірте `VERSION.txt = 1.10.0`.
5. Встановіть requirements, виконайте compile/static/targeted tests.
6. Commit + `git push heroku main`.
7. Перевірте `/health`, Telegram `/start`, усі 3 participant hubs, Participant 360 і `⚙️ Налаштування`.

Детальні команди: `COMMANDS_V1100.txt`.
