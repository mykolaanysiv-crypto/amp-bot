# Оновлення АМП XP до v1.6.9

## Що змінює схема БД
v1.6.9 додає тільки нові таблиці:
- `surveys`
- `survey_questions`
- `survey_responses`
- `user_status_change_requests`

Стандартний `release: python -m scripts.heroku_release` / `db.init()` створить їх ідемпотентно. **Не запускайте повторно `migrate_sqlite_to_postgres.py`.**

## Перед deploy
1. Переконайтесь, що Git робочої папки чистий.
2. Створіть Heroku PostgreSQL backup та скачайте його локально.
3. Збережіть `.env` поза репозиторієм.
4. Перенесіть v1.6.9 через `rsync` без `.git`, `.env`, `.venv`, `data`.
5. Перевірте `VERSION.txt` і `app/version.py` → `1.6.9`.
6. `python -m compileall -q app scripts` та `git diff --check` мають пройти без помилок.

## Після deploy
Перевірте:
- `/health` → `1.6.9`;
- `heroku ps` → web process `up`;
- у логах немає `Traceback`, `OperationalError`, `ProgrammingError`, `IntegrityError`, `TemplateNotFound`;
- web: `📋 Опитування` відкривається, чернетка створюється, питання додаються, публікація створює Telegram-розсилку;
- Telegram: кнопка `📋 Опитування`, проходження тестового опитування, одноразове XP;
- Події: `Чернетка / Відкрита реєстрація / Реєстрацію закрито / Перенесено / Завершено / Скасовано`;
- `🤝 Запросити друга` → PNG QR-запрошення;
- звичайний admin при зміні статусу учасника створює запит, а superadmin бачить його у `Учасники` і підтверджує/відхиляє;
- темна тема `📄 Звіти`, картки `Ідеї`, а також відступи в `Звернення / Розсилки / Модерація / Бейджі`.

## Вова Дорош
Профіль учасника **не дублюється**. Для Telegram/системної ролі використайте:

```bash
heroku run -a amp-bot-ver-1-5-0 -- python scripts/promote_existing_user.py --name "Вова Дорош" --role admin
```

Скрипт змінює роль існуючого запису. Якщо знайде кілька збігів — нічого не змінить і покаже АМП-ID для уточнення.

Для web-панелі персональний логін створюється окремо:

```bash
python scripts/add_staff_account.py \
  --app amp-bot-ver-1-5-0 \
  --username vova.dorosh \
  --display-name "Вова Дорош"
```

Пароль генерується автоматично та виводиться один раз у Terminal. Його не слід додавати в Git або надсилати у відкритий чат.
