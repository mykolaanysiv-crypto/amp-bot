# AMP XP v1.22.0 — Working Iteration 4

## Статус
Повна вихідна кодова база, призначена лише для локального тестування. Це не підтверджений production-реліз. `VERSION.txt` зберігає чинний номер до релізного затвердження.

## Зміни
- Додано редагування вже створених запитань опитувань через спільний modal на сторінці деталей опитування. Оригінальні `form`, CSRF, method, action та обробники не клонуються, а тимчасово переносяться в dialog.
- Посилено відновлення DOM у випадку помилки під час відкриття `showModal()`, захищено повернення фокусу після закриття.
- Адаптивне оформлення редактора запитань та кнопок дій на малих екранах.
- Додано статичні регресійні тести для цих сценаріїв.

## Перевірки
- `node --check app/web/static/ux22_modals.js`: PASS.
- `python3 -m compileall -q app`: PASS.
- `pytest -q tests/test_ux22_static_contract.py tests/test_ux22_followup_contract.py tests/test_ux22_iteration3_contract.py tests/test_ux22_iteration4_contract.py`: 12 PASS.
- ZIP CRC check: PASS (перевірити після пакування).

## Не перевірено
Реальні браузерні взаємодії, PostgreSQL 18 integration, Telegram, QA різних браузерів, QR/XP end-to-end, деплой та restore backup. Усі внесені зміни потребують локальної ручної перевірки до деплою.
