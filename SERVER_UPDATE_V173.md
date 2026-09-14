# AMP XP v1.7.3 — оновлення production

## Що важливо перед deploy

v1.7.3 переносить web-авторизацію з plaintext Config Vars у таблицю `web_staff_accounts` з PBKDF2-хешами та додає серверні сесії. Старі `WEB_ADMIN_PASSWORD` і `WEB_STAFF_ACCOUNTS_JSON` потрібні лише на ПЕРШОМУ успішному запуску v1.7.3, щоб створити хешовані DB-акаунти. Після перевірки входу їх треба видалити з Heroku Config Vars.

Для обов'язкового 2FA суперадміна має бути заданий `SUPERADMIN_IDS` — одноразовий код надсилається в Telegram одному із цих ID.

## Безпечна послідовність

1. Зробити Heroku PostgreSQL backup.
2. Перенести файли v1.7.3 поверх робочого Git-каталогу, не копіюючи `.env`, `.venv`, `data` і `.git`.
3. `pip install -r requirements.txt`.
4. Перевірити `VERSION.txt` та `app/version.py` = `1.7.3`.
5. `python -m compileall -q app scripts` і `git diff --check`.
6. Commit + `git push heroku main`.
7. Перевірити `/health` → `1.7.3` і логи.
8. Увійти web-суперадміном: після пароля прийде Telegram 2FA-код; після першого входу система попросить змінити пароль.
9. Перевірити входи іменних admin-акаунтів; кожен legacy акаунт також має змінити тимчасовий пароль.
10. Тільки після успішної перевірки видалити plaintext bootstrap-змінні:

```bash
heroku config:unset WEB_ADMIN_PASSWORD WEB_STAFF_ACCOUNTS_JSON -a amp-bot-ver-1-5-0
```

`WEB_ADMIN_USERNAME`, `SUPERADMIN_IDS`, `WEB_SESSION_SECRET` та інші не секретні/службові налаштування залишити.

## Нові security-сторінки

- `/admin/account` — пароль, 2FA, активні сесії користувача.
- `/admin/security` — тільки superadmin: акаунти, reset пароля, завершення всіх сесій.

## Міграція БД

Стандартний release `python -m scripts.heroku_release` виконує `Base.metadata.create_all()` та additive-ініціалізацію. Додаються `web_staff_accounts` і `web_admin_sessions`. Повторно запускати `migrate_sqlite_to_postgres.py` НЕ потрібно.

## Rollback

Якщо web-login не працює, не видаляйте legacy Config Vars. Виконайте rollback до попереднього Heroku release, перевірте `SUPERADMIN_IDS`/BOT_TOKEN і повторіть deploy після виправлення.
