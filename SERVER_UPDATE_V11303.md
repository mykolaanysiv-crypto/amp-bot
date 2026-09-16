# AMP XP / «АМПасадори» v1.13.0.3 — Telegram Navigation & Web Localization Hotfix

## Причина релізу

Після Architecture Completion користувацький smoke виявив три UX-регресії:

1. `/menu` і активний `/start` не відкривали головний екран та не оновлювали reply-клавіатуру. Причина — lazy import у вкладеному `app.handlers.start_flow.common` залишився на неправильному relative рівні та шукав `app.handlers.start_flow.participant` замість `app.handlers.participant`.
2. `/smart` був заявлений як корисний сценарій персональних можливостей, але як Telegram-команда фактично не був зареєстрований.
3. Назви винагород у Telegram обрізалися utility helper-ом до 28 символів; у web-панелі залишалися окремі англомовні користувацькі назви після архітектурного refactor.

## Виправлення Telegram

- `app/handlers/start_flow/common.py`: активний `/start` і `/menu` тепер коректно імпортують participant facade через `from .. import participant` і відкривають актуальний екран «Головна».
- Після `/menu` або `/start` активний учасник отримує поточну `main_menu(...)` reply-клавіатуру, тому старе розміщення кнопок замінюється актуальним.
- `app/handlers/participant_opportunities.py`: додано `Command("smart")`; команда відкриває персоналізований список можливостей і перед показом оновлює matching.
- `app/bot_runtime.py`: `/smart` додано до публічного BotCommand menu як «Персональні можливості».
- `app/telegram_middleware.py`: `/smart` є навігаційною командою і безпечно виходить із незавершеного FSM-сценарію.
- `/help` описує `/smart`.
- `app/keyboards.py`: винагороди використовують `entity_button_text`, тому назва винагороди більше не обрізається кодом до 28 символів.

## Локалізація web-панелі

Видимі службові англомовні назви переведено українською, зокрема:

- `Participant 360` → `Профіль учасника 360°`;
- `Referrals` → `Запрошення друзів`;
- `Timeline` → `Хронологія`;
- `SEASONS & HISTORY` → `СЕЗОНИ ТА ІСТОРІЯ`;
- `Freeze` → `Заморозка серії`;
- `SLA прострочено` → `Прострочено строк реагування`;
- технічні формулювання `granular permission`, `manual override`, `check-in window` замінено зрозумілими українськими формулюваннями.

Notification Center більше не друкує відомі внутрішні `type/entity/status` коди як користувацькі назви: вони проходять через централізований `label(...)`. Технічні коди помилок/діагностики та назви протоколів/брендів (`Telegram`, `QR`, `XP`, `PDF`, `Excel`, `Heroku`, `Monobank`) не перейменовуються.

## Regression guards

- Додано `tests/test_v11303_telegram_web_ux_hotfix.py`.
- `production_preflight` блокує release, якщо:
  - знову зламається relative import для `/start`/`/menu`;
  - `/smart` зникне з BotCommand/handler/FSM navigation;
  - винагороди знову почнуть обрізатися через `compact_button_text`;
  - повернуться відомі англомовні UI labels у web templates.
- Historical source-inspection tests синхронізовано з новими українськими labels, щоб повний GitHub regression suite перевіряв актуальний UI, а не старі англомовні назви.

## Сумісність і БД

- SQLAlchemy schema: без змін, **54 таблиці**.
- Нова Alembic migration: відсутня.
- Production Alembic head: `20260915_0002`.
- XP, Content Views, Notification Center, security/ACL, backup, Clock/time hardening і scheduler architecture не змінюють контракт.
- Compatibility facades Architecture Completion зберігаються.
- Production PostgreSQL не очищати й не створювати заново.

## QA

- `python -m compileall -q app scripts tests migrations` — PASS.
- `python -m scripts.production_preflight` — PASS (`Production preflight OK for AMP v1.13.0.3`).
- Core v1.13.0.3 + architecture/hotfix focused suite — PASS.
- Affected historical UI/source regression tests — PASS.
- Full dependency/runtime suite має бути підтверджений GitHub Actions, де встановлюється `requirements-dev.txt` і піднімається PostgreSQL 16.

## Production acceptance

1. GitHub Actions — повністю зелений, включно з `python -m scripts.heroku_release`.
2. Deploy — зелений.
3. `web.1` і `worker.1` — `up`.
4. `alembic current` — `20260915_0002 (head)`.
5. `/health/ready` — HTTP 200 `ready`.
6. `/health/dependencies` — HTTP 200 після startup grace.
7. Telegram smoke:
   - активний `/start` відповідає та показує актуальну клавіатуру;
   - `/menu` відповідає та оновлює клавіатуру;
   - `/smart` відкриває персональні можливості;
   - «Винагороди» показують повні назви.
8. Web smoke: Dashboard, Учасники, Сезони, Календар, Notification Center та Event Cockpit без відомих англомовних UI labels.
