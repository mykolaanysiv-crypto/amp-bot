# AMP XP v1.22.2 — CI backup permissions hotfix

## Внесено
- Запуск restore-скрипта у двох GitHub Actions workflow через `bash`, незалежно від Unix executable bit у ZIP.
- Скрипт `verify_backup_restore.sh` має файловий режим 755 в архіві; додано обов’язкову перевірку імені Heroku app.
- Збережені запобіжники `AMP_ALLOW_TEMP_RESTORE=1` та `RESTORE_DATABASE_URL`; відновлення виконується в ізольовану БД.
- Додано regression-тести захисту restore workflow.
- Узгоджено версію 1.22.2 у `VERSION.txt`, `VERSION_CHECK.txt`, fallback і cache keys.

## Не завершено
- Веблічильник непрочитаних повідомлень потребує окремої моделі read/unread, серверних маршрутів і UX-тестів.
- Візуальна перевірка усіх авторизованих сторінок і dark mode не проведена.
- Не підтверджено тестове відновлення реального backup та інтеграційне тестування Telegram, PostgreSQL, QR/XP.
- Не виконано production deployment.
