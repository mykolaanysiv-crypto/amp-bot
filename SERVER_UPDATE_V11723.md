# AMP XP v1.17.2.3 — Quick XP Builder, Survey Editor & Quest Card UX

## 1. Quick XP

- Web-форма стала type-aware: `quiz`, `video`, `poll`, `comment` показують тільки свої поля.
- Для `quiz` можна створити до 30 питань одразу, а потім додавати, редагувати, видаляти й переставляти їх окремо.
- Кожне питання мініквізу має власні варіанти, правильну відповідь і XP (1–20).
- Перша відповідь учасника на питання фіксується в `quick_xp_answers`; повторне натискання не може повторно нарахувати XP.
- Правильна відповідь нараховує XP одразу; після всіх питань створюється одна `quick_xp_completion` із сумою фактично отриманих XP.
- Існуючі старі одно-питальні `quiz` автоматично переносяться в `quick_xp_questions` через Alembic.
- Поле «Порядок / 100» прибране з UI. Список challenge сортується: recommended first → newest first.

## 2. Weekly cap

- Default змінено `15 → 30 XP`.
- У Web → «Налаштування» додано секцію `⚡ Швидкі XP`.
- Ключ runtime settings: `runtime.quick_xp.weekly_cap`.
- Допустимий діапазон: `1…500 XP`.
- Зміна не потребує deploy або міграції.

## 3. Опитування

- Назва та опис винесені в окремий блок і зберігаються окремим action `/identity`.
- XP, дедлайн і аудиторія лишилися в окремому блоці «Налаштування».
- У draft кожне питання можна окремо редагувати: текст, тип, required, варіанти, фото.
- Питання можна переставляти кнопками `↑ / ↓` без ручного поля sort order.
- Кнопка редагування уніфікована як `✏️ Редагувати` / `edit-action-button`.

## 4. Layout / quests

- Додано spacing/layout hardening для Quick XP, surveys і expanded edit drawers.
- Квестові картки у двоколонковій сітці розтягуються до однакової висоти.
- Медіаблок квесту має стабільну висоту, зображення не накладається на контент.
- Основні дії квесту: `👁 Детально` + `✏️ Редагувати`, як у подіях.

## 5. Schema

Alembic head: `20260921_0012`.

Нові таблиці:
- `quick_xp_questions`
- `quick_xp_answers`

Unique idempotency:
- `uq_quick_xp_question_user (question_id, user_id)`

## 6. Перевірки збірки

- `python -m compileall -q app scripts tests migrations` — PASS
- `python -m scripts.production_preflight` — PASS
- Jinja parse — 58/58 PASS
- `alembic heads` → `20260921_0012`
- focused regression/source tests для v1.17.2.3 + Quick XP v1.17.2.2 + меню — PASS
- повний DB-backed `pytest` у build-container не запускається через відсутні `aiogram`/`aiosqlite`; його потрібно виконати у project `.venv` та GitHub Actions.
