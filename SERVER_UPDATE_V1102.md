# АМП XP / «АМПасадори» v1.10.2 — 🧩 Granular Permissions & Telegram Home

## Що змінено

### 1. Granular permissions

Замість одного великого рівня доступу для `admin/superadmin` система підтримує окремі дозволи. Ключові приклади:

- Participants: `participants.view`, `participants.edit`, `participants.approve`;
- Events: `events.create`, `events.edit`, `events.delete`;
- XP: `xp.award`;
- Reports: `reports.basic_export`, `reports.sensitive_export`;
- Broadcast: `broadcast.send`;
- Moderation: `moderation.manage`;
- окремі manage/view права для квестів, волонтерства, активностей, можливостей, опитувань, ідей, кейсів, аналітики, Notification Center, гейміфікації, аудиту, System Health і Settings.

Superadmin у `🛡 Безпека та права доступу` може налаштувати персональний набір дозволів для:

- web staff account;
- Telegram staff user (`coordinator/admin/superadmin`).

Можна повернутися до default permissions поточної ролі. Superadmin не можна звузити custom ACL — це break-glass account.

### 2. Реальний server-side enforcement

- sidebar/кнопки ховаються за permissions;
- direct URL перевіряється middleware, тобто прихованої кнопки недостатньо для обходу;
- global search і `🔔 Потребує уваги` не повертають модулі без доступу;
- Telegram admin callbacks і фінальні FSM actions повторно перевіряють permission;
- malformed explicit permission JSON fail-closed;
- при role change custom ACL staff скидається до role defaults.

### 3. Participants privacy

`participants.edit` дозволяє редагувати базові нечутливі дані учасника. Телефон/email/дата народження/vulnerability/document/consent workflow не відкриваються цим правом автоматично. Повний sensitive profile/media зберігає чинні обмеження security baseline.

`reports.sensitive_export` окремо дозволяє розширені event/donor exports із журналюванням.

### 4. Telegram Home

`🏠 Головна` перероблена в інформативний dashboard:

- привітання по імені;
- AMP-ID і роль;
- lifetime XP, прогрес до наступного рівня, wallet XP;
- league / season XP;
- weekly streak;
- volunteer hours;
- найближча подія;
- найближчий quest deadline;
- оновлення звернень;
- нові Smart Opportunities.

В основному меню напряму доступні `🤝 Запросити друга` і `🆘 Звернення`.

## База даних

Нових таблиць немає. Схема залишається **47 таблиць**. Additive/idempotent додаються лише nullable TEXT-поля:

- `users.staff_permissions_json`;
- `web_staff_accounts.permissions_json`.

Повторний перенос SQLite → PostgreSQL не потрібний. `scripts.heroku_release` виконає additive upgrade.

## Встановлення

Див. `COMMANDS_V1102.txt`. Перед deploy обов'язково зробити PostgreSQL backup і виконати локально повний `pytest -q`.

## Rollback

Оскільки зміни БД additive і nullable, rollback коду не потребує destructive rollback схеми. Нові колонки можуть безпечно лишитися в PostgreSQL.
