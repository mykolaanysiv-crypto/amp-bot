# Оновлення AMP XP до v1.6.4

Версія v1.6.4 додає окремий модуль **📊 Аналітика** без зміни структури production-бази даних. Показники формуються наживо з наявних таблиць.

## Перед оновленням

```bash
cd ~/Downloads/amp_bot_v155
git status
heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
heroku pg:backups:download -a amp-bot-ver-1-5-0 -o ~/Downloads/amp_before_v164.dump
```

## Перенесення файлів

Якщо `amp_bot_v164` вже є папкою у `Downloads`:

```bash
rsync -av \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='data' \
  ~/Downloads/amp_bot_v164/ \
  ~/Downloads/amp_bot_v155/
```

## Залежності та перевірка

У v1.6.4 додано `matplotlib` для серверного формування PDF зі справжніми графіками.

```bash
cd ~/Downloads/amp_bot_v155
source .venv/bin/activate
pip install -r requirements.txt
cat VERSION.txt
python -m compileall -q app scripts
git diff --check
```

Очікувана версія: `1.6.4`.

## Commit і deploy

```bash
git add -u
git add app/analytics.py app/web/templates/analytics.html app/web/templates/analytics_detail.html COMMANDS_V164.txt SERVER_UPDATE_V164.md
git status
git commit -m "AMP XP v1.6.4 automated analytics"
git push heroku main
```

## Перевірка production

```bash
heroku ps -a amp-bot-ver-1-5-0
curl https://amp-bot-ver-1-5-0-9632a1434a6d.herokuapp.com/health
heroku logs --tail -a amp-bot-ver-1-5-0
```

Після deploy перевірити `/admin/analytics`, загальний та окремі Excel/PDF, а також `🛠 Адмін-панель → 📊 Аналітика` у Telegram.

> Не запускайте повторно `migrate_sqlite_to_postgres.py`. У v1.6.4 немає нових таблиць або колонок.
