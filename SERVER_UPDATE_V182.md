# AMP XP / «АМПасадори» v1.8.2 — 🎨 Participant 360 UI Polish

## Що змінюється

v1.8.2 — невеликий UI/UX patch поверх v1.8.1. Business logic, lifecycle, security, notifications, аналітика, reporting, referral guard, donor registration templates та reliability-механізми не змінюються.

### 1. Квести й активності в Participant 360

Було: `🎯 Квести` та `⚡ Активності` відображалися в одному двоколонковому блоці вкладки `Активність`. На частині ширин web-панелі таблиці могли стискатися, накладатися або мати незручні переноси.

Стало:

- `🎯 Квести` — окрема вкладка;
- `⚡ Активності` — окрема вкладка;
- кожна таблиця використовує повну доступну ширину;
- заголовки, статус і дата вирівняні по центру;
- довгі назви переносяться всередині своєї колонки, а не заходять на сусідню;
- на вузькому екрані таблиця має контрольований горизонтальний scroll замість зламаного layout.

### 2. KPI Participant 360

8 KPI тепер мають явний `display:grid`:

- desktop: **4 картки в ряд**, тобто 4×2;
- tablet/mobile: адаптивно 2 колонки;
- однакова висота карток;
- компактніший текст;
- число і підпис відцентровані;
- довгі підписи безпечно переносяться всередині картки.

Це виправляє ситуацію, коли `Події / Квести / Задачі / Активності / Опитування / Ідеї / Бейджі / Referrals` могли відображатися по одній великій картці на ряд.

### 3. Вкладки Participant 360

- однакові висота, відступи та центрування;
- текст кнопки не обрізається;
- на desktop вкладки вирівняні по центру;
- на mobile доступний горизонтальний scroll без переносу кнопок у хаотичний layout.

### 4. Дублювання XP

Прибрано окремий нижній блок `🧾 Останні операції з досвідом`, тому що він дублював ті самі транзакції, які вже є у вкладці `XP` Participant 360.

При цьому **ручне нарахування XP не видалено** — блок `⚡ Нарахувати досвід` залишається робочим.

### 5. CSS cache

У `base.html` cache-buster змінено на:

```text
/static/admin.css?v=1.8.2
```

Це важливо, щоб після deploy браузер не використовував старий cached CSS v1.8.0/v1.8.1.

## База даних

У v1.8.2:

- нових таблиць немає;
- нових полів немає;
- міграція схеми не потрібна;
- metadata залишається **44 таблиці**.

Стандартний Heroku release залишається:

```text
python -m scripts.heroku_release
```

Ручний SQLite → PostgreSQL migration запускати **не потрібно**.

## Перед deploy

```bash
cd ~/Downloads/amp_bot_v155

heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
```

Після копіювання v1.8.2 у робочий Git-каталог:

```bash
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

cat VERSION.txt
python -c "from app.version import APP_VERSION; print(APP_VERSION)"

python -m compileall -q app scripts tests
pytest -q tests/test_v181_features.py tests/test_v182_ui.py
git diff --check
```

Очікувана версія: `1.8.2`.

## Deploy

```bash
git add -A
git diff --cached --check
git commit -m "AMP XP v1.8.2 Participant 360 UI polish"
git push heroku main
```

## Після deploy

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku ps -a amp-bot-ver-1-5-0
curl -s https://amp-bot-ver-1-5-0-9632a1434a6d.herokuapp.com/health
heroku logs -n 200 -a amp-bot-ver-1-5-0
```

Очікувана версія `/health`: `1.8.2`.

## Що перевірити вручну

1. Відкрити `Учасники → Детально`.
2. У Participant 360 переконатися, що 8 KPI стоять як **4 + 4**.
3. Перевірити окремі вкладки `🎯 Квести` і `⚡ Активності`.
4. Переконатися, що довгі назви не накладаються на статус/дату.
5. Перевірити вкладку `XP`.
6. Переконатися, що окремої дубльованої таблиці `Останні операції з досвідом` внизу більше немає.
7. Перевірити, що `⚡ Нарахувати досвід` залишився і працює.
8. Перевірити desktop та мобільну/вузьку ширину браузера.
