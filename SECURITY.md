# Security baseline v1.7.3

- Web-паролі: PBKDF2-SHA256 hash у `web_staff_accounts`; plaintext Config Vars використовуються лише для першого bootstrap/migration і після перевірки входів мають бути видалені.
- 2FA: обов’язкова для `superadmin`, опційна для `admin`; одноразовий код надсилається в Telegram і має обмежений TTL/кількість спроб.
- Login protection: 5 невдалих паролів → 15 хв блокування, події журналюються.
- CSRF: усі unsafe `/admin` запити потребують session token.
- Sessions: серверні `web_admin_sessions`, revoke окремої/всіх сесій, роль/active перевіряються з БД.
- Media: public / participant-private / staff-private / superadmin-private; невідомі категорії secure-by-default. Приватні файли мають `Cache-Control: private, no-store`.
- Audit: login/logout/failed login/2FA, password operations, sensitive media/export, XP, badges, roles, streaks, consent та destructive actions.
- Analytics/report privacy: чутливі агрегати 1–4 відображаються як `<5`; exact count не передається у графік.

# Безпека та приватність

- Не публікуйте `.env`, `BOT_TOKEN`, `WEB_ADMIN_PASSWORD`, `WEB_SESSION_SECRET`.
- Для постійного розгортання використовуйте HTTPS та PostgreSQL.
- Каталог `AMP_DATA_DIR` містить операційні дані, фото та резервні копії; обмежте доступ до нього.
- Розділ **«Звернення»** може містити проблемні питання, інциденти або інформацію про безпеку. Не вносіть зайві чутливі персональні дані та надавайте доступ лише відповідальним особам.
- `internal_note` у зверненнях є внутрішньою інформацією і не відправляється учаснику; `admin_response` — навпаки, призначена для учасника.
- Перед оновленням або суттєвою зміною даних виконайте `python scripts/backup_all.py`.
- При локальному SQLite v1.3 використовує постійну папку `~/AMP_Bot_Data`; код нової версії не повинен містити саму БД.

## Чутливі категорії профілю

v1.4.3 може зберігати добровільно надані категорії вразливості, зокрема інформацію про інвалідність, ветеранський/сімейний статус, складні життєві обставини та ЛГБТ+ належність. Це чутливі персональні дані.

- Поле є необов’язковим; учасник може обрати «Не бажаю зазначати».
- Не виводьте ці категорії у публічний QR, рейтинг, реферальні повідомлення або відкриті списки.
- Доступ до вебпанелі з такими даними надавайте лише уповноваженим працівникам/координаторам.
- Не експортуйте та не передавайте ці дані партнерам без належної правової підстави та визначеної мети.
- Видаляйте або виправляйте дані на запит учасника відповідно до ваших внутрішніх правил та чинних вимог щодо захисту персональних даних.

## v1.5.0 — звернення, фото та модерація

- Фото звернень можуть містити чутливу інформацію. Не публікуйте каталог `uploads/requests` окремо від контрольованого застосунку.
- Доступ до web-панелі має бути лише у уповноваженої команди.
- Тимчасове блокування використовуйте для порушень правил спільноти; причина і строк фіксуються в журналі дій.
- Не використовуйте блокування як заміну процедурі реагування на серйозні безпекові інциденти.

## v1.5.1 — централізована модерація

- Тимчасові блокування зберігаються окремими записами історії (`ban_records`).
- У причинах блокування не слід фіксувати зайві чутливі персональні дані або принизливі характеристики.
- Telegram-модерація доступна лише ролі суперадміністратора.
- У web-панелі модерацію слід вважати функцією рівня суперадміністратора; доступ до web-облікового запису необхідно захищати надійним паролем та HTTPS у production.

## Ролі web-доступу (v1.6.0)
- `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD` — суперадміністратор: повні персональні дані, редагування карток, модерація, журнал доступу та розширені Excel.
- `WEB_STAFF_ACCOUNTS_JSON` — додаткові облікові записи звичайних адміністраторів. Вони працюють з базовими даними, але не бачать дату народження, стать, Telegram ID чи категорії вразливості; телефон та email маскуються.
- Не використовуйте один спільний логін для кількох працівників, якщо важливо розуміти, хто саме відкривав дані: кожному працівнику створюйте окремий обліковий запис.
- Розширений Excel містить персональні та чутливі дані. Не пересилайте його у відкриті чати та не зберігайте у загальнодоступних папках.

## Резервні копії PostgreSQL на Heroku
Для production PostgreSQL локальний `backup_all.py` не є заміною серверної резервної копії. У v1.6.0 додано helper:

```bash
./scripts/heroku_schedule_backups.sh amp-bot-ver-1-5-0 "03:00 Europe/Kyiv"
```

Перевірка розкладу:

```bash
heroku pg:backups:schedules --app amp-bot-ver-1-5-0
```

Періодично перевіряйте, що резервні копії справді створюються, оскільки збій розкладу сам по собі не є механізмом сповіщення.

## v1.6.8 — документи та згоди
- Скан/файл батьківської згоди відображається лише суперадміністратору.
- У PostgreSQL такі файли зберігаються як `MediaAsset(category="consents")`; публічний `/media/{id}` не віддає їх неавторизованим користувачам.
- У локальному режимі consent-файли зберігаються в `AMP_DATA_DIR/private/consents`, поза публічним `/uploads`.
- Зміна/відкликання згоди не стирає історію статусів: вона фіксується в `consent_history` разом із датою, версією та автором зміни.


## v1.11.0 — registration checkpoints, Monobank і admin cache

- Незавершена реєстрація може містити персональні дані. Її draft зберігається у `registration_journeys.draft_ciphertext` у зашифрованому вигляді; plaintext questionnaire-поля у таблицю не дублюються.
- Ключ шифрування checkpoint-чернетки похідний від `WEB_SESSION_SECRET`. Не публікуйте і не логайте цей секрет; зміна секрету робить старі незавершені чернетки нерозшифровуваними, але не пошкоджує вже створені профілі.
- `MONOBANK_TOKEN` зберігайте лише у Heroku Config Vars / захищеному `.env`; він не має потрапляти у Git, audit payload, UI або повідомлення про помилки.
- Monobank integration не повертає response body провайдера в user-facing/internal error text та не зберігає внутрішній jar account id після sync.
- На `/admin` застосовується `Cache-Control: no-store, private` і `Pragma: no-cache`, щоб чутливі сторінки не кешувалися браузером/proxy.
- Ім’я/опис платника, receipt/comment та інші donor-sensitive поля в web маскуються для всіх ролей, крім `superadmin`; операційні суми, дати та AMP-ID залишаються доступними відповідно до прав.
- Registration funnel і feedback conversion зберігають/показують агреговані operational metrics, а не окремий новий профіль чутливих категорій.

---

## v1.12.0 — production security / observability hardening

- Heroku web і Telegram worker розділені на окремі процеси, тому аварія polling worker не повинна завершувати web dyno.
- Structured logs проходять через `SensitiveDataFilter`: значення `BOT_TOKEN`, `MONOBANK_TOKEN`, `DATABASE_URL`, `WEB_SESSION_SECRET`, `SENTRY_DSN`, `HEROKU_API_KEY` редагуються перед виводом.
- Web отримує correlation `X-Request-ID`; request body не записується middleware.
- Optional Sentry працює з `send_default_pii=False`; cookies, Authorization, X-Token, email/IP/username видаляються через `before_send`.
- Notification Center failure alert надсилає лише агреговані counts/types/ID range і не містить body повідомлень або контактів.
- Backup warning містить лише стан/вік verified marker; backup data не копіюються у Telegram.
- `Gamification 2.0` є read/analysis-only: модуль не викликає `add_xp`, не змінює league thresholds і rewards.

## Backup verification automation (v1.12.1.5)
- Heroku API key залишається тільки в GitHub Actions Secrets; застосунок не отримує його у Config Vars.
- AMP зберігає лише timestamp/label підтвердженої копії, а не backup-файл чи Heroku credential.
- Initial grace не підміняє backup: статус лишається непідтвердженим, просто без негайного false-positive paging.


## v1.17.2 — field encryption, retention та restore verification
- Найчутливіші текстові поля профілю зберігаються через application-level Fernet encryption (`EncryptedText`).
- Рекомендований окремий root secret: `FIELD_ENCRYPTION_KEY`; якщо його немає, використовується `WEB_SESSION_SECRET`.
- Для rotation спочатку вкажіть старий ключ у `FIELD_ENCRYPTION_PREVIOUS_KEYS`, новий — у `FIELD_ENCRYPTION_KEY`, запустіть `python -m scripts.rotate_field_encryption`, а після перевірки приберіть previous key.
- Не логувати значення encryption keys: observability redaction включає обидва encryption Config Vars.
- Retention cleanup не видаляє audit/consent/XP/attendance history або профілі.
- Backup вважається verified лише після restore в ізольований PostgreSQL та перевірки `users` + `alembic_version`.
- Data Integrity Center не виконує автоматичне злиття дублікатів чи видалення orphan records.


## v1.17.2.1 — duplicate-removal safeguards

- Видалення дубліката доступне лише суперадміністратору та лише для participant/ambassador профілів.
- Server-side повторно перевіряється фактичний duplicate match; одного прихованого form field недостатньо.
- Потрібне явне підтвердження словом `ВИДАЛИТИ`.
- Профіль з історичними FK-зв’язками не hard-delete: він архівується як `deleted_permanent`, щоб зберегти цілісність історії.
- Пряма зміна статусу через quick control дозволяє лише `pending / active / inactive`; блокування та видалення не обходять існуючі workflow.

## v1.17.2.4 — підтвердження квестів

- Фото-підтвердження квестів зберігаються у media category `quest_proofs` з рівнем `staff-private`; анонімний/public media route їх не віддає.
- Ручне підтвердження квесту без participant submission доступне тільки `superadmin`, вимагає текстову причину та журналюється в audit log.
- Live-sync вебпанелі не підміняє блок, якщо користувач редагує поле або форма має незбережені зміни.
