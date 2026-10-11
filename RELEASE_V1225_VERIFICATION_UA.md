# AMP XP v1.22.5 — звіт про фактично виконані зміни

**Статус: кандидат, НЕ production-ready, НЕ повне виконання 20 пунктів.** Джерело — наданий v1.22.4 ZIP, не підтверджено синхронізацію з актуальним Git HEAD.

## Виконано
- `app_shell.js`: повне оновлення HTML для live regions тепер не частіше ніж раз на 60 секунд (було 5 секунд); вимкнене для прихованої/offline вкладки, має блокування паралельних fetch. Це знижує частоту потенційно дорогих повторних GET до 12 разів за постійно відкритої сторінки з live-region, **але не є гарантією зниження CPU БД в 12 разів**.
- `web_inbox.js`: захист від паралельних запитів і обмеження запитів unread badge до не частіше ніж раз на 30 секунд за активації вкладки.
- `notifications.py`: три окремі агрегатні SQL-запити для KPI статусів доставки замінено на один GROUP BY; семантика queued+retry/sent/failed збережена.
- `ux_release_1224.css`: охайний адаптивний рядок повідомлень, перенесення довгих текстів, reduced-motion.
- Поточна версія 1.22.5 узгоджена у VERSION файлах, static tokens, preflight і документації.
- Існуючі рішення з v1.22.4 збережено: одна кнопка сповіщень, bulk read, sidebar, reset.

## Фактичні перевірки
- `python -m scripts.production_preflight`: PASS.
- `python -m scripts.release_consistency_check`: PASS; Alembic head 20261011_0019.
- `python -m compileall -q app scripts`: PASS.
- `node --check app/web/static/app_shell.js` та `web_inbox.js`: PASS.
- `pytest` цільового набору v1.22.4/v1.22.3/v1.22.2/v1.21.0/v1.20.2: 31 PASS після виправлення версійного assert.
- Повний pytest: BLOCKED (ModuleNotFoundError aiogram під час collection).

## НЕ підтверджено і НЕ завершено
- Останній стан GitHub та Heroku; production PG 100% utilization; `pg_stat_activity`, `pg_stat_statements`, locks і query plans відсутні. **Неможливо стверджувати, що 100% PostgreSQL навантаження усунуто.**
- Browser Playwright/Safari з авторизованими тестовими акаунтами, усі 20 UX-завдань, повне охоплення dark mode, responsive overflow.
- Реальний HTTP тест bulk mark read, інтеграція Telegram, XP/QR, PostgreSQL 18 та тест відновлення backup.
- Повна CI/CD збірка й автоматичний деплой не запускалися.

## Безпечні наступні кроки
1. На актуальній Git-гілці порівняти зміни з PATCH, особливо файли backend і static; не копіювати весь архів поверх новіших змін.
2. Встановити всі dev-залежності; виконати повний pytest і integration PostgreSQL 18.
3. У staging перевірити UI через Playwright у світлій/темній темі; перевірити ролі, права, CSRF, bulk read.
4. Для PostgreSQL зібрати read-only метрики (pg_stat_activity, wait events, connection utilization, top SQL via pg_stat_statements якщо увімкнено); лише потім вирішувати щодо індексів/пулу/плану БД.
5. Відновити backup в ізольовану PG18 та отримати зелений CI до merge; **жодного автодеплою**.

## Міграції
Нових міграцій немає; поточний Alembic head `20261011_0019`.
