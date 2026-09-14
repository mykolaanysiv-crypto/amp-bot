# АМП XP / «АМПасадори» v1.8.2.4 — Continuous Telegram Scanner & Notification Fix

## 1. QR Scanner тепер справді працює всередині Telegram

Основний scanner переведено на Telegram Mini App із native QR popup.

Шлях:
`Telegram → Адмін-панель → 📷 QR Scanner → подія`.

Кнопка конкретної події є `WebApp`-кнопкою. Після натискання відкривається Mini App, який автоматично викликає Telegram native QR scanner.

### Continuous scanning

Scanner не закривається після першого QR. Telegram продовжує сканувати нові коди, доки адміністратор сам не закриє камеру або Mini App.

Додано debounce, щоб один бейдж, який довго залишається в кадрі, не відправляв десятки однакових scan-запитів.

## 2. Підтвердження кожного сканування в чаті бота

Після scan адміністратор отримує Telegram-повідомлення:

- ПІБ;
- AMP-ID;
- назву події;
- `Зареєстрований: так/ні`;
- `Відмічений на події: так/ні`.

Для registered/reserved/checked_in participant attendance підтверджується чинним idempotent workflow.

Для незареєстрованого учасника scanner не реєструє його мовчки. У чаті приходить кнопка:
`✅ Зареєструвати та підтвердити`.

## 3. Безпека Telegram Mini App

POST scanner endpoint не довіряє event ID або Telegram user ID із браузера. Він перевіряє підписаний Telegram `initData` через HMAC-SHA256 із `BOT_TOKEN`, перевіряє `auth_date`, після чого окремо перевіряє, що Telegram-користувач має активну роль coordinator/admin/superadmin.

Звичайний web-admin cookie не використовується як scanner-auth.

## 4. Browser compatibility

Основний scanner більше не залежить від browser `BarcodeDetector`. QR-камера відкривається native Telegram client API, тому поведінка не залежить від Chrome/Safari/Firefox/Edge усередині web admin.

Browser-camera scanner на event detail залишається optional fallback.

## 5. Виправлено подвійне повідомлення про оновлення

`_announce_version_update()` тепер використовує distributed DB `job_lock` із ключем поточної `APP_VERSION`.

Це закриває startup race, коли два процеси могли одночасно побачити старе `last_announced_app_version` і створити два однакові broadcast campaign.

`SystemSetting.last_announced_app_version` збережено як другий рівень idempotency.

## База даних

Нових таблиць або полів немає. Схема залишається 44 таблиці.

## Після deploy перевірити

1. `/health` → `1.8.2.4`.
2. Telegram → Адмін-панель → 📷 QR Scanner.
3. Натиснути подію — Mini App має відкритися й камера має запуститися автоматично.
4. Просканувати registered participant → камера залишається відкритою, у чаті приходить підтвердження.
5. Не закриваючи scanner, просканувати другого учасника.
6. Просканувати unregistered participant → у чаті має бути `Зареєструвати та підтвердити`.
7. Перезапустити dyno / deploy ще раз із тією ж версією → повторне version notification не повинно створюватися.
