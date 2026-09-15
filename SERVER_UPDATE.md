# Оновлення АМПасадори до v1.11.1 на Heroku

v1.11.1 оновлюється поверх поточної production-версії без локального запуску. Схема БД залишається 53 таблиці; production PostgreSQL очищати або створювати заново не потрібно.

## 1. Перейдіть у робочу Git-папку

```bash
cd ~/Downloads/amp_bot_v1103
```

```bash
git status
git remote -v
```

Якщо `heroku` remote відсутній:

```bash
heroku git:remote -a amp-bot-ver-1-5-0
```

## 2. Backup production PostgreSQL

```bash
heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
```

## 3. Візьміть поточний Heroku commit за основу

Переконайтеся, що важливі локальні зміни вже збережені. Потім:

```bash
git fetch heroku main
git reset --hard heroku/main
```

## 4. Розпакуйте v1.11.1

```bash
rm -rf /tmp/amp_bot_v1111_release
mkdir -p /tmp/amp_bot_v1111_release
unzip -q ~/Downloads/amp_bot_v1111.zip -d /tmp/amp_bot_v1111_release
```

## 5. Накладіть реліз поверх робочого Git-репозиторію

```bash
rsync -av --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  /tmp/amp_bot_v1111_release/amp_bot_v1111/ \
  ./
```

## 6. Перевірте версію та секрети

```bash
cat VERSION.txt
git check-ignore .env
git status --short
git diff --stat
```

Очікувана версія: `1.11.1`.

Перевірка Monobank без показу секрету:

```bash
if [ -n "$(heroku config:get MONOBANK_TOKEN -a amp-bot-ver-1-5-0)" ]; then
  echo "✅ MONOBANK_TOKEN встановлено"
else
  echo "❌ MONOBANK_TOKEN відсутній"
fi
```

`MONOBANK_TOKEN` повторно вводити не потрібно, якщо він уже є у Config Vars. `WEB_SESSION_SECRET` під час звичайного update не змінюйте.

## 7. Commit і deploy

```bash
git add -A
git status
git commit -m "Upgrade AMP to v1.11.1 Event Operations & Reporting 2.0"
git fetch heroku main
git push heroku HEAD:main
```

Не використовуйте `--force`, якщо оновлення зроблено за цим сценарієм.

## 8. Перевірте production release

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku ps -a amp-bot-ver-1-5-0
heroku logs --tail -a amp-bot-ver-1-5-0
```

## 9. Smoke-check після deploy

1. `/health` показує `1.11.1`.
2. Відкрити будь-яку подію у web — угорі є **Операційний центр**.
3. Перевірити етапи: зареєстровані / черга / відмітка / підтверджено / XP / зворотний зв’язок.
4. Перевірити стан QR-сканера та масові дії.
5. `Звіти` → сформувати звіт за ISO-тиждень і за місяць.
6. У PDF/XLSX є точний `Дані станом на ... Europe/Kyiv`, потокові/моментні KPI, воронки, Data Quality і визначення.
7. Для вибірки з однією точкою немає line chart — показуються KPI.
8. `Безпека / Журнал доступу` — колонка `Хто` читається повністю, слова не розбиваються.
9. Перевірити Monobank sync — v1.10.4.1 hotfix `jar/<id>` збережено.

Якщо release або web dyno падає — не очищайте БД. Збережіть traceback з Heroku logs; за потреби виконайте rollback code release через Heroku Releases.
