# AMP XP / «АМПасадори» v1.8.2.1 — 📅 Calendar & Event Operations

## Що змінюється

v1.8.2.1 — функціональний patch поверх v1.8.2. Security, Participant 360, lifecycle, durable Telegram outbox/retry, idempotent XP та підтвердження attendance збережені.

### 1. Єдиний календар

`Календар` у web має три режими:

- **День**;
- **Тиждень**;
- **Місяць**.

У календарі агрегуються:

- події;
- старт/дедлайн квестів;
- дедлайни волонтерських задач;
- старт/дедлайн опитувань;
- дедлайни можливостей;
- строки відповіді кейсів;
- дедлайни реалізації ідей/мініпроєктів;
- streak freezes.

Кожен тип має **іконку + власний accent**, тому тип не визначається лише кольором. Є переходи `Назад / Сьогодні / Далі`.

### 2. Web QR Scanner

На сторінці події є кнопка:

```text
📷 Почати check-in
```

На HTTPS-сторінці браузер запитує доступ до камери телефона. Scanner використовує `getUserMedia` та browser `BarcodeDetector` для QR. Для браузерів, де QR detector недоступний, залишено ручний fallback — можна вставити `AMP-0008` або текст QR.

Підтримується персональний QR/profile token учасника та AMP-ID.

Якщо учасник уже зареєстрований/reserved/checked-in, scan проводить check-in і підтверджує attendance через чинний idempotent workflow.

Якщо учасник не зареєстрований, web показує його ПІБ/AMP-ID і кнопку:

```text
Зареєструвати та підтвердити
```

Ця дія створює/відновлює registration, фіксує check-in і підтверджує attendance одним захищеним admin workflow.

### 3. Waitlist та 2-годинний резерв

Для подій із `capacity` місце вважається зайнятим статусами `registered / reserved / checked_in / attended`.

Коли вільних місць немає, Telegram пропонує:

```text
Місць наразі немає.
Хочеш стати в чергу?

⏳ Стати в чергу
```

Waitlist працює FIFO: найстаріший учасник черги отримує місце першим.

Після скасування/звільнення місця:

- учасник переходить `waitlisted → reserved`;
- місце резервується на **2 години**;
- через durable Telegram outbox надходить повідомлення;
- кнопка `✅ Підтвердити місце` переводить reservation у звичайну реєстрацію;
- якщо 2 години минули, reservation повертається в waitlist, а місце пропонується наступному.

### 4. Attendance workflow

Web і Telegram використовують чіткі стани участі:

- `registered` → **Зареєстрований**;
- `cancelled` → **Скасував**;
- `waitlisted` → **У черзі**;
- `reserved` → **Місце зарезервовано**;
- `checked_in` → **Відмічено присутність**;
- `attended` → **Був присутній**;
- `no_show` → **Не прийшов**.

Після завершення event window непідтверджені `registered/reserved` автоматично переводяться в `no_show`.

У web detail події додані окремі KPI: зареєстровані, waitlist, були присутні, не прийшли.

### 5. Безпека камери

`Permissions-Policy` для web дозволяє camera лише для власного origin:

```text
camera=(self)
```

Microphone/geolocation лишаються вимкненими. Scanner працює лише в admin session і через CSRF-захищений POST.

## База даних

Нових таблиць немає. Загальна metadata — **44 таблиці**.

До `event_registrations` additive/idempotent додаються nullable поля:

- `waitlisted_at`;
- `waitlist_promoted_at`;
- `reservation_expires_at`;
- `no_show_at`.

Додаються індекси для `waitlisted_at` та `reservation_expires_at`.

Стандартний Heroku release сам виконує upgrade/init:

```text
python -m scripts.heroku_release
```

**Не запускайте вручну SQLite → PostgreSQL migration.**

## Перед deploy

```bash
cd ~/Downloads/amp_bot_v155

heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
```

Після копіювання v1.8.2.1 у робочий Git-каталог:

```bash
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

cat VERSION.txt
python -c "from app.version import APP_VERSION; print(APP_VERSION)"

python -m compileall -q app scripts tests
pytest -q tests/test_v181_features.py tests/test_v182_ui.py tests/test_v1821_calendar_event_ops.py
git diff --check
```

Очікувана версія: `1.8.2.1`.

## Deploy

```bash
git add -A
git diff --cached --check
git commit -m "AMP XP v1.8.2.1 Calendar and Event Operations"
git push heroku main
```

## Після deploy

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku ps -a amp-bot-ver-1-5-0
curl -s https://amp-bot-ver-1-5-0-9632a1434a6d.herokuapp.com/health
heroku logs -n 200 -a amp-bot-ver-1-5-0
```

Очікувана версія `/health`: `1.8.2.1`.

## Що перевірити вручну

1. `Календар` → День / Тиждень / Місяць.
2. Перевірити всі 8 типів календарних елементів та переходи по них.
3. Відкрити подію з телефона по HTTPS → `📷 Почати check-in` → дозволити camera.
4. Просканувати QR зареєстрованого учасника — attendance має підтвердитися один раз.
5. Просканувати незареєстрованого — має з'явитися `Зареєструвати та підтвердити`.
6. Створити capacity-подію, заповнити всі місця та перевірити Telegram `⏳ Стати в чергу`.
7. Скасувати одну реєстрацію — першому в waitlist має прийти 2-годинний reservation.
8. Перевірити `✅ Підтвердити місце`.
9. Перевірити прострочення reservation і перехід місця наступному в черзі.
10. Після завершення тестової події перевірити `Не прийшов` для непідтверджених registration.
11. Перевірити, що XP/години при повторному підтвердженні не дублюються.
