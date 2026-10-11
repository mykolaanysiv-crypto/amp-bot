# AMP XP v1.22.4 — фактичний стан релізного кандидата

**Джерело:** наданий архів `AMP_XP_v1.22.3_WEB_INBOX_SOURCE_CANDIDATE.zip`. Це не синхронізований HEAD вашої Git-гілки і не production-деплой.

## Внесено в код
- Прибрано другу верхню кнопку дзвоника. Основний персональний дзвоник із реальним unread counter залишено.
- Для sidebar використано напрямну стрілку та CSS-поворот на 180° при `sidebar-collapsed`; відцентровані її та навігаційні іконки.
- Усунуто кореневу причину дубльованої кнопки «Скинути»: `app_shell.js` більше не створює reset, якщо він уже є у формі.
- Додано серверну `POST /admin/web-inbox/read-all`, яка вставляє `web_notification_reads` лише для пов'язаного учасника поточного web-акаунта; повторний виклик безпечний завдяки `ON CONFLICT DO NOTHING`. Стан доставки Telegram не змінюється. Форма містить CSRF поле.
- Додано `ux_release_1224.css`: узгодження анімацій, focus/press, ширини фільтрів, кнопок, чекбоксів, заголовків розсилок, таблиць та деяких темних поверхонь; це структурні CSS-коригування, не підтверджений повний редизайн.
- Виправлено застарілий інтеграційний тест `CURRENT_HEAD`: автоматично читає єдиний Alembic head; попередню production-ревізію збережено.
- Узгоджено номер версії в `VERSION.txt`, `VERSION_CHECK.txt`, `app/version.py`, шаблонах, preflight, README і HEROKU_DEPLOY. Нової міграції немає; поточна ревізія `20261011_0019`.

## Фактичні тести
- `python -m scripts.production_preflight`: PASS.
- `python -m scripts.release_consistency_check`: PASS, head `20261011_0019`.
- `python -m compileall -q app scripts`: PASS.
- `node --check app/web/static/app_shell.js` і `web_inbox.js`: PASS.
- `pytest -q tests/test_v1224_ux_inbox.py tests/test_v1223_web_inbox.py tests/test_v1222_release_and_backup.py tests/test_v1210_product_experience.py tests/test_v1202_ui_polish_interaction.py`: 31 PASS.
- `pytest -q --ignore=tests/integration`: НЕ ЗАВЕРШЕНО: у середовищі відсутня залежність `aiogram` (3 errors during test collection). Це не доказ успішного повного регресійного тестування.

## Невиконані / непідтверджені обов'язкові вимоги
- Реальні браузерні скриншоти, анімації та темна тема у всіх модулях, модальні вікна та мобільні таблиці не пройшли end-to-end browser testing; потрібен запуск Playwright у тестовому середовищі, зі справжнім контентом.
- UI-виправлення для ідей, нагород, серій, календаря, усіх розсилок/модалок та всіх таблиць потребують точкової перевірки в браузері; CSS сам собою не підтверджує відсутність переповнення.
- PostgreSQL 100% utilization: без реальних метрик `pg_stat_activity`, `pg_stat_statements`, lock waits та даних про план Essential неможливо визначити причину й довести зниження навантаження; не слід змінювати індекси або пул навмання.
- Перевірка реальних Telegram deliveries, XP/QR, backup restore та Alembic migration on isolated PostgreSQL 18 не проводилася.
- CI/Dependabot failure logs потрібно аналізувати за конкретними logs: самі позначки failed не визначають першопричини.
- Backend bulk read перевірено структурно, але не HTTP/DB інтеграційним тестом.

## Безпека та розгортання
1. Порівняти патч із актуальною Git-гілкою; не копіювати ZIP поверх новіших незбережених змін.
2. Створити окрему гілку; встановити `requirements-dev.txt`, прогнати unit+integration tests на тестовій PostgreSQL 18.
3. Перевірити браузерну регресію, сценарії з двома web-акаунтами, доступ до чужих сповіщень та CSRF.
4. Проаналізувати production DB метрики лише read-only інструментами; не експериментувати з backup або індексами у production.
5. Запустити повні GitHub Actions, потім окремо погодити merge/deploy. Не розгортати цей кандидат автоматично.

## Ризики
Широкі CSS-селектори для таблиць і чекбоксів можуть змінити верстку інших модулів; required responsive review. `POST /admin/web-inbox/read-all` у гілці з великим inbox може виконати масову транзакцію: потрібно заміряти latency/locks на staging та розглянути батчинг. Не заявляти production-ready до цих перевірок.
