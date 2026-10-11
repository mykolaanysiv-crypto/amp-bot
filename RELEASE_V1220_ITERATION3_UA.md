# AMP XP v1.22.0 — Working Iteration 3

## Статус
Повний вихідний архів для локальної перевірки, **не production**. Вихідна кодова база v1.21.0 з накопиченими змінами ітерацій v1.22.0. VERSION.txt навмисно залишено `1.21.0` до затвердження релізу.

## Нова зміна Iteration 3
- Усі форми створення, які перенесені в модальні вікна, приховуються одним CSS-правилом `[data-ux22-collapsed="true"]`, включно з прямими form-елементами модулів «Сезони» та «Донати».
- При відкритті діалогу приховування тимчасово знімається; при закритті коректно відновлюється.
- Додано 3 статичні тести для цього контракту.

## Перевірки
- `node --check app/web/static/ux22_modals.js` — PASS.
- `python3 -m compileall -q app` — PASS.
- `pytest -q tests/test_ux22_static_contract.py tests/test_ux22_followup_contract.py tests/test_ux22_iteration3_contract.py` — 9 PASSED (статичні тести).

## Не перевірено
Повне E2E в браузері, HTTP POST з реальною базою PostgreSQL 18, бот/Telegram, резервне копіювання та відновлення, Heroku deploy smoke. Динамічні редактори всіх типів та повний page-by-page редизайн ще не завершені.

## Рекомендація
Тестувати локально в окремій базі; production не оновлювати, поки не пройдені інтеграційні тести й restore-verified backup.
