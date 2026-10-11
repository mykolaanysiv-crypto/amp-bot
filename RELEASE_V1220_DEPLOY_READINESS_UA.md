# AMP XP v1.22.0 — перевірки перед деплоєм

Статус: **Deployment candidate / НЕ підтверджено Production Ready**. Це архів повного вихідного коду з напрацюваннями v1.22.0. Відсутні доступи до Heroku, production DB та Telegram; жодного живого деплою, відновлення backup чи наскрізної перевірки не проводилось.

## Що перевірено локально
- Узгоджено `VERSION.txt`, `VERSION_CHECK.txt`, `app/version.py`, release checker та cache-busting статичних ресурсів до `1.22.0`.
- `python -m scripts.release_consistency_check` — PASS.
- `python -m compileall -q app scripts migrations tests` — PASS.
- Обрані 28 статичних UX/регресійних pytest-тестів — PASS.
- Node JS smoke для форм, оболонки, взаємодій, CSP, polish — PASS (не заміняють реальний браузер).
- Версійні Telegram-повідомлення у `app/web/broadcast_runtime.py` адресуються активним користувачам із роллю `SUPERADMIN`, зі стійким dedupe key і DB lock. Це читання коду, не Telegram end-to-end перевірка.

## Не підтверджено
- Повну автоматичну перевірку `pytest -q`, PostgreSQL 18 migrations/integration, весь CI GitHub.
- Playwright/Safari UI кожної сторінки й форми; WCAG audit.
- Реальний Telegram delivery, QR check-in, XP concurrency, винагороди/донати.
- Валідність backup і відновлення на ізольованому PostgreSQL 18.
- Heroku release startup, /health/live після релізу й rollback.
- Візуальна відповідність КОЖНОГО з 65 шаблонів всім шістьом еталонам; не заявляти повний редизайн завершеним.

## Безпечний порядок розгортання (тільки після зеленої CI)
1. Створити окрему Git-гілку `release/v1.22.0`, розпакувати джерела в корінь репозиторію, перевірити diff.
2. Запустити GitHub Actions `ci.yml`, усунути будь-які FAIL, отримати green для Python, Node, Postgres 18, Alembic, dependency/security gates.
3. Запустити інтеграційні тести Telegram/QR/XP на stage-боті і тестовій базі; не надсилати реальні повідомлення користувачам.
4. Зробити Heroku PGBackup production DB, відновити на окремій ізольованій PG18, перевірити схему і таблиці; використовувати `scripts/verify_backup_restore.sh` лише на ізольованій базі.
5. Створити staging app і перевірити release-phase, `GET /health/live`, `GET /health/ready` якщо маршрут існує, login/permissions/QR/XP і ручний браузерний UX.
6. Лише після тестів, backup і схвалення — merge в main/production deploy; перевірити версію, health, логи, Telegram superadmin notification, виконати post-deploy smoke.
7. У разі помилки — rollback застосунку; окремо оцінити сумісність DB, не робити сліпого downgrade чи restore production.

## Мінімальні команди (локально в репозиторії)
```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
python -m scripts.dependency_lock_check
python -m scripts.release_consistency_check
python -m scripts.production_preflight
python -m compileall -q app scripts migrations tests
pytest -q --ignore=tests/integration
# Середовище з TEST_DATABASE_URL на ізольовану PostgreSQL 18:
pytest -q tests/integration
```

Важливо: `git push` і Heroku production deployment не здійснювалися. Запуск live-інтеграцій без тестових credentials небезпечний.
