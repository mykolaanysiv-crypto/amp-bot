# Оновлення АМПасадори до v1.11.0 на Heroku

Сценарій нижче призначений для існуючого локального Git-репозиторію, уже підключеного до Heroku `amp-bot-ver-1-5-0`. Локально запускати застосунок не потрібно.

## 1. Перейдіть у робочу Git-папку

Наприклад, якщо ви продовжуєте використовувати попередню папку:

```bash
cd ~/Downloads/amp_bot_v1103
```

Перевірте remote:

```bash
git status
git remote -v
```

Якщо `heroku` відсутній:

```bash
heroku git:remote -a amp-bot-ver-1-5-0
```

## 2. Backup production PostgreSQL

```bash
heroku pg:backups:capture -a amp-bot-ver-1-5-0
heroku pg:backups -a amp-bot-ver-1-5-0
```

## 3. Візьміть точний поточний Heroku commit за основу

Переконайтеся, що локальних незбережених змін немає, після чого:

```bash
git fetch heroku main
git reset --hard heroku/main
```

`.env` має бути у `.gitignore`; ця команда не повинна додавати його до Git.

## 4. Розпакуйте v1.11.0 у тимчасову папку

```bash
rm -rf /tmp/amp_bot_v1110_release
mkdir -p /tmp/amp_bot_v1110_release
unzip -q ~/Downloads/amp_bot_v1110.zip -d /tmp/amp_bot_v1110_release
```

## 5. Накладіть реліз поверх робочої Git-папки

```bash
rsync -av --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  /tmp/amp_bot_v1110_release/amp_bot_v1110/ \
  ./
```

## 6. Перевірте версію і секрети

```bash
cat VERSION.txt
git check-ignore .env
git status --short
```

Очікувана версія: `1.11.0`. `.env` не повинен бути staged.

Перевірка Monobank без виводу токена:

```bash
if [ -n "$(heroku config:get MONOBANK_TOKEN -a amp-bot-ver-1-5-0)" ]; then
  echo "✅ MONOBANK_TOKEN встановлено"
else
  echo "❌ MONOBANK_TOKEN відсутній"
fi
```

Не змінюйте `WEB_SESSION_SECRET` під час звичайного оновлення: він використовується також для шифрування нових registration checkpoints.

## 7. Commit і deploy

```bash
git add -A
git status
git commit -m "Upgrade AMP to v1.11.0"
git fetch heroku main
git push heroku HEAD:main
```

`--force` не потрібен, якщо крок `reset --hard heroku/main` був виконаний перед накладанням релізу.

## 8. Перевірте release

```bash
heroku releases -a amp-bot-ver-1-5-0
heroku ps -a amp-bot-ver-1-5-0
heroku logs --tail -a amp-bot-ver-1-5-0
```

Release phase запускає штатну ініціалізацію/міграції БД. Схема v1.11.0 має 53 таблиці.

## 9. Smoke-check після deploy

Перевірте:

1. `/health` показує `1.11.0`.
2. Нова реєстрація показує progress і може бути продовжена після переривання.
3. Telegram-меню має потрібний порядок; `⚡ Швидкі дії` відсутній.
4. Feedback після події проходиться короткими кнопками; повторне reminder-повідомлення не дублюється.
5. Web Dashboard показує `Сьогодні`, `Операційний стан`, registration funnel і feedback conversion.
6. `💙 Донати → Оновити дані` синхронізує банку Monobank; секретний token не відображається в UI/log error.
7. Звичайний admin не бачить donor-sensitive text; superadmin бачить його за наявності даних.

Якщо release phase або web dyno падає — не очищайте БД. Збережіть traceback із `heroku logs --tail` і відкотіть code release через Heroku Releases за потреби.
