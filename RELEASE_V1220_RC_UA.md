# AMP XP v1.22.0 — інтеграційний пакет, не повна збірка за ТЗ

## Реалізовано
- Одна modal-система для створення квестів, волонтерських задач, можливостей, опитувань, винагород, бейджів, активностей і Quick XP.
- Форму переміщуємо в dialog *у тому самому DOM*, тому зберігаються валідація браузера, file upload, CSRF, POST action і наявні listeners.
- Модальні форми редагування для карток, що використовують details.event-edit-details.
- Responsive layout, sticky actions, попередження про незбережені зміни.
- Технічні повідомлення про версію обмежено ACTIVE + superadmin + наявний Telegram ID. Існуючі DB-lock і per-user dedupe збережено.

## НЕ завершено
- Не виконано наскрізне оновлення всіх сторінок та форм згідно Design Bible; не перебудовано UX усіх модулів.
- Форми Quick XP вже мають frontend-перемикання *існуючих* типів quiz/video/poll/comment; нові серверні типи не додавалися.
- Не завершено інтеграційні PostgreSQL 18 тести, Playwright visual QA та live-перевірки Telegram.
- Існуючі доставлені або вже поставлені в чергу широкомовні version notices цим патчем не скасовуються; перед деплоєм окремо перевірити outbox.
- Version.txt і production-версію не підвищено: маркування 1.22 RC означає лише робочу гілку змін, а не здійснений реліз.

## Перевірки
- Python compileall: пройдено.
- Node syntax `--check` UX JS: пройдено.
- pytest tests/test_broadcast_retry_schema.py: blocked — відсутній `aiosqlite` у середовищі.
- Browser E2E, PG18/backup, Heroku smoke: не виконано.

## Як локально перевірити
1. Розпакуйте ZIP у нову папку; не замінюйте працюючий застосунок.
2. Налаштуйте окрему dev-базу, Python env, конфігурацію згідно чинного README і встановіть залежності.
3. Перевірте миграції, `pytest`, вхід за всіма ролями; окремо відкрийте `/admin/quests`, `/admin/tasks`, `/admin/opportunities`, `/admin/surveys`, `/admin/rewards`, `/admin/quick-xp`.
4. Перевірте створення/редагування, скасування зі зміненими полями, завантаження файлів, QR і XP.
5. Перед деплоєм зробіть backup + test restore; пройдіть CI, PG18 integration, ручний Safari/Chrome QA.

## Архітектурний ризик
JS переміщує наявну форму в діалог; це не змінює server contracts, однак page-specific JS може припускати незмінний DOM parent. Обов'язковий браузерний regression test кожного модуля.
