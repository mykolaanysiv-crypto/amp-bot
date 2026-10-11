# AMP XP v1.22.0 — наступна ітерація робочої збірки

## Важливо
Це **working / unreleased**, не підтверджена production-збірка. Повний редизайн за Design Bible і перевірка з реальною PostgreSQL 18 базою та Telegram не завершені. `VERSION.txt` залишено без змін.

## Зміни після попередньої working-збірки
- Спільний modal manager краще обробляє повторні submit: після проходження стандартної browser validation форма отримує pending state; повторне відправлення блокується. Кнопка не переводиться в `disabled`, щоб її `name/value` не зникало зі стандартного HTTP submit.
- При закритті діалогу відновлюються DOM-оригінал форми, можливість повторного відкриття, доступність кнопки, а також стан `pendingSubmit`.
- Покращені keyboard focus styles, прокручування діалогу та `prefers-reduced-motion`.
- Додано окремі статичні регресійні тести цих контрактів.

## Перевірки в середовищі підготовки
- `node --check app/web/static/ux22_modals.js` — PASS.
- `python3 -m compileall -q app` — PASS.
- `pytest -q tests/test_ux22_static_contract.py tests/test_ux22_followup_contract.py` — PASS (6 тести), **статичні**, не браузерні.

## Необхідно до production
- Повне E2E у браузері з HTTP POST і серверною валідацією; відхилені POST / CSRF errors.
- Інтеграційні тести PostgreSQL 18, Telegram і webhook/outbox, тестування ролей і permission guards.
- Перевірка історичних широкомовних повідомлень версій у pending outbox.
- Backup + restore-verified, CI і Heroku smoke.
- Завершення page-by-page дизайн-редизайну всіх сторінок.

## Деплой
**Не завантажувати у production до повного тестування.**
