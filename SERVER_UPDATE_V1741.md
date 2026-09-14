# AMP XP / АМПасадори v1.7.4.1 — production update

## Що це за реліз

v1.7.4.1 — функціональний patch-реліз поверх v1.7.4 Reliability & Architecture. Захисний шар v1.7.3, idempotent XP/години, distributed scheduler locks, durable Telegram outbox і retry розсилок збережені.

Основні зміни: share/registration links подій, Telegram QR check-in для координаторів/адмінів, donor registration templates DOCX/XLSX, технічний SHA-256 код підтвердженої участі, 30-денний referral clawback та новий каталог сервісних винагород.

## Перед оновленням

1. Перевірте, що поточний production стабільний і `/health` відповідає.
2. Створіть Heroku PostgreSQL backup і переконайтесь, що він завершився успішно.
3. Збережіть локальний `.env` окремо; не копіюйте його з ZIP.
4. Не запускайте `migrate_sqlite_to_postgres.py`: реліз використовує additive/idempotent release migration.
5. Не видаляйте security Config Vars v1.7.3/v1.7.4: `BOT_TOKEN`, `DATABASE_URL`, `WEB_SESSION_SECRET`, `SUPERADMIN_IDS`, `PUBLIC_BASE_URL` тощо.
6. `PUBLIC_BASE_URL` має бути коректним production URL, інакше share/registration links подій вестимуть не на той хост.

## Зміни БД

Кількість таблиць не змінюється: **44**.

### `events`
- `share_token VARCHAR(64)` — окремий випадковий token для публічного посилання; не використовується як check-in token;
- `registration_template_path VARCHAR(500)`;
- `registration_template_name VARCHAR(255)`;
- `registration_template_type VARCHAR(16)`.

### `event_registrations`
- `attendance_signature VARCHAR(64)`;
- `attendance_signature_version VARCHAR(16)`;
- `attendance_signature_created_at TIMESTAMP`;
- `attendance_confirmed_by_user_id INTEGER`.

### `referrals`
- `revoked_at TIMESTAMP`;
- `revoke_reason TEXT`;
- `clawback_xp INTEGER`.

Для старих подій без `share_token` startup bootstrap створює token автоматично. Міграція ідемпотентна.

## Події та посилання

- Web-картка події має блок `📤 Поділитися подією`.
- Публічний URL: `/event/{share_token}`.
- Публічна сторінка не містить персональних даних учасників і не публікує check-in token/QR.
- Кнопка реєстрації переводить у Telegram deep-link `start=event_{share_token}`.
- У Telegram учасник може переслати подію другу.
- Admin/superadmin у Telegram мають `🔗 Посилання на подію` і отримують як public page URL, так і прямий Telegram registration deep-link.

## QR відмітки у Telegram

Coordinator/admin/superadmin мають окрему кнопку `🔳 QR відмітки`:

`Адмін-панель → 🔳 QR відмітки → активна подія → PNG QR`

QR використовує чинний `checkin_token` події. Після сканування Telegram фіксує `checked_in`; XP і години нараховуються тільки після підтвердження адміністратором/координатором.

## Реєстраційна форма донора

У detail події можна завантажити:

- `.docx`;
- `.xlsx`;
- до 20 МБ.

Система шукає типові заголовки (`ПІБ`, `Телефон`, `Email`, `Населений пункт`, `Статус`, `Підпис/Цифровий код підтвердження` тощо) та заповнює наявну таблицю, зберігаючи структуру й стилі настільки, наскільки це дозволяє формат шаблону. Підтримуються placeholders:

`{{event_title}}`, `{{event_date}}`, `{{event_time}}`, `{{event_datetime}}`, `{{event_location}}`, `{{event_xp}}`, `{{participants_count}}`.

Якщо таблицю шаблону неможливо надійно розпізнати, оригінальний контент не видаляється: для XLSX додається аркуш `АМП — учасники`, для DOCX — таблиця наприкінці документа. Якщо шаблон взагалі не завантажений, використовується стандартний AMP XLSX.

З міркувань v1.7.3 security regular web-admin отримує data-minimized експорт; sensitive поля заповнюються лише для superadmin.

## SHA-256 код підтвердження участі

Після переходу `checked_in → attended` кожній конкретній event registration створюється унікальний 64-символьний SHA-256 confirmation code. Він генерується лише один раз і не змінюється при повторному confirm. Код видно в web-таблиці події та реєстраційних експорт-файлах.

> Це внутрішній технічний ідентифікатор/код підтвердження АМП. Він **не є КЕП, УЕП або власноручним юридичним підписом учасника**.

## Referral clawback — 30 днів

Якщо referral уже був винагороджений, а invited user переходить у `inactive` не пізніше 30 днів після нарахування referral reward:

- сторнується рівно `Referral.xp_reward`;
- створюється negative XP transaction категорії `referral_reversal`;
- referral переходить `rewarded → revoked`;
- зберігаються `revoked_at`, `revoke_reason`, `clawback_xp`;
- повторна обробка не списує XP вдруге;
- inviter отримує durable Telegram notification.

Якщо Telegram повертає `TelegramForbiddenError` під час durable outbox або broadcast delivery, active participant/ambassador автоматично переходить у `inactive`; після цього застосовується та сама 30-денна referral перевірка. Telegram Bot API не надсилає окрему подію «користувач видалив бота», тому автоматичне визначення відбувається при першій невдалій спробі доставки після блокування/видалення чату.

## Нові винагороди

При bootstrap, якщо винагороди з такими назвами ще не існують, додаються:

- 1 година гри на приставці — 5 XP;
- 1 год оренди кімнати в молодіжному просторі — 15 XP;
- оренда проєктора та екрану — 45 XP;
- 1 год оренди всього молодіжного простору — 50 XP;
- нова гра PlayStation AA / старше 10 років — 50 XP;
- нова гра PlayStation AAA — 75 XP;
- настільні ігри додому на 7 днів — 100 XP;
- PlayStation ексклюзив / новинка до 1 року — 100 XP;
- 4 год оренди молодіжного центру — 150 XP.

Вони мають `reward_type=service`: після того як попередня заявка виконана адміністратором, учасник може замовити цю сервісну винагороду знову.

## Після deploy

Перевірте:

1. `/health` → `1.7.4.1`.
2. `/admin/system-health` → DB/Bot/Scheduler без критичних помилок.
3. Відкрити тестову подію у web → `📤 Поділитися` → публічна сторінка відкривається.
4. Telegram admin → `🔗 Посилання на подію` → public URL + direct registration link.
5. Telegram coordinator/admin → `🔳 QR відмітки` → PNG завантажується.
6. Скан QR активним учасником → `checked_in`; підтвердити → `attended`, XP один раз, SHA-256 code створений.
7. Прикріпити тестовий `.xlsx`/`.docx` donor template → завантажити заповнений файл та перевірити дизайн/таблицю.
8. Перевірити каталог винагород: 9 нових сервісних позицій.
9. На тестовому referral, винагородженому менше 30 днів тому, встановити invited user `inactive` → referral XP сторнується один раз і inviter notification з’являється в outbox.

## Rollback

Код можна відкотити стандартною командою Heroku rollback. Нові колонки additive й можуть залишатися в БД — попередня v1.7.4 їх не використовує.
