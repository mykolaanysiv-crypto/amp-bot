# AMP XP v1.20.2 — UI Polish, Navigation & Interaction 3.0

Статус: **Release Candidate** до проходження повного GitHub Production Gate, restore-verified backup, Heroku health/version smoke та ручного visual QA.

Версія застосунку: **1.20.2**  
Alembic head: **20261010_0018**  
Нова міграція БД у v1.20.2: **відсутня**.

## Мета релізу
v1.20.2 не є черговим перефарбуванням. Реліз виправляє interaction debt після великого redesign: справжні вкладки замість anchor-scroll, стабільний sidebar/account identity, модальні edit-flow, searchable participant picker, єдина SVG icon system, виразні hover/motion/toast стани, кращий контраст і ефективніше використання desktop-простору.

## Основні зміни
- «Профіль / Досягнення / Безпека / Сесії» реалізовані як справжні ARIA tabs (`tablist/tab/tabpanel`), а не посилання на секції сторінки.
- Активна вкладка зберігається через `?tab=...`; підтримуються ArrowLeft/ArrowRight/Home/End та focus без примусового scroll.
- Додано анімований indicator та panel transitions з підтримкою `prefers-reduced-motion`.
- Account hero показує identity користувача, role як контекст, avatar та profile actions; layout не залежить від розміру фото.
- Sidebar більше не дублює окремий «Мій кабінет» у navigation; footer лишається компактним, topbar має account dropdown.
- Avatar використовується з одного profile source в hero/topbar/sidebar compact identity; image layout фіксований через square sizing/object-fit.
- Profile та avatar editing використовують dialog-based UX; avatar dialog має preview, file chooser/dropzone та відокремлену danger action для видалення.
- Додано `interaction.js` і `interaction.css` як окремий progressive-enhancement layer без SPA rewrite.
- Додано animated toasts, сильніші card/button hover states, motion tokens, dialog/tab/account-menu transitions.
- Participant profile linking більше не вимагає знати numeric DB id: додано accessible searchable combobox і захищений superadmin endpoint пошуку за AMP-кодом/ПІБ/username.
- Help Center отримав category tabs; текстовий пошук лишається cross-category.
- Calendar та Idea detail переведені на єдиний SVG icon macro; системні emoji прибрані з web templates. Emoji у user-generated/Telegram content не змінювалися.
- Idea detail зберігає production workflow, але отримує узгоджений visual stepper/icon presentation.
- Додано adaptive content widths, responsive grids, fluid typography, кращий contrast для gradient/muted/placeholder states.

## Свідомо змінена UI-вимога та regression tests
До v1.20.2 частина старих source-regression tests вимагала буквальні emoji у web templates (`👁`, `✅`, `❌`, `🔁`, `✏️`, `⚡`, `📲`, `🌐` тощо). У v1.20.2 production-вимогу свідомо змінено: **системна web-іконографіка має бути єдиною SVG-системою, а не emoji**. Тому лише ці web-UI assertions оновлено на перевірку тексту/маршрутів/семантики. Telegram keyboard/user-generated emoji requirements не послаблювалися.


## CSP-safe interaction architecture
Під час фінального hardening усі executable inline `<script>` та HTML event-handler attributes (`onclick`, `onchange`, `oninput` тощо) винесено з Jinja templates у зовнішні static JS modules. Нові page-specific модулі: `page_behaviors.js`, `event_detail.js`, `telegram_event_scanner.js`, `analytics.js`, `analytics_detail.js`. Це дозволяє зберігати interaction-rich UI без повернення до inline JavaScript або послаблення CSP.

Historical source tests, які перевіряли буквальну наявність inline JavaScript, оновлено лише там, де production-вимога свідомо змінилася на external CSP-safe JavaScript. Функціональні вимоги — realtime polling, sharing, scanner behavior, analytics drill-down — продовжують перевірятися у нових зовнішніх модулях.

## Завершення системної web-іконографіки
Фінальний icon pass прибрав із web templates залишкові системні glyph/emoji на кшталт pending/download/return/refresh/start/stop/external-link і замінив їх на єдиний Jinja SVG macro. Символи контенту (`№`, `360°`, copyright) та emoji у user-generated/Telegram text не трактуються як product icons і не змінювалися.

## Security / privacy / backend guarantees
Не змінено семантику XP, attendance, QR, quests, badges, rewards, events, media lifecycle, permissions, roles, privacy suppression, CSRF, CSP, 2FA, WebAuthn/passkeys, audit trail, backup verification чи schema drift.

Participant search endpoint захищений `guard_superadmin`; UI hiding не використовується як security boundary. Modal submit продовжує використовувати існуючі server-side route/CSRF/permission checks.

## Database
v1.20.2 не додає schema migration. Поточний head лишається:

```text
20261010_0018
```

Rollback UI-релізу не потребує Alembic downgrade.

## Перевірено в build environment
Фактично виконано і пройдено:
- `python -m scripts.dependency_lock_check`;
- deterministic `python -m scripts.build_admin_css`;
- `python -m scripts.release_consistency_check`;
- `python -m scripts.production_preflight`;
- `python -m compileall -q app scripts migrations tests`;
- Alembic CLI: один head `20261010_0018`;
- Jinja parse: 65 templates;
- JavaScript smoke: `admin_forms`, `app_shell`, `experience`, `interaction`, `csp_externalization`;
- `node --check` для всіх нових external interaction/page modules;
- CSP source gate: 0 inline executable `<script>` і 0 HTML event-handler attributes у web templates;
- targeted v1.20.2/CSP historical regression group: 27 tests PASS;
- broader UI/source regression group: усі runnable tests PASS, 1 intentional skip; 2 DB-backed tests не стартували лише через відсутній `aiosqlite` у build sandbox;
- web-template system-icon scan: після фінального pass залишилися лише content symbols (`№`, `°`, `©`), без system emoji/glyph icons.
- patch apply до чистої v1.20.1 baseline та byte-level tree equivalence: PASS (471 файлів).

Окремо спробовано повний `pytest -q --ignore=tests/integration`: collection зупиняється на 3 модулях через відсутній `aiogram` у build sandbox. Це environment limitation, а не позначений PASS.

Не називаються PASS у build sandbox:
- Ruff — module unavailable;
- pip-audit — module unavailable;
- clean-project `pip check` — global build environment має сторонній `moviepy`/`Pillow` conflict;
- full runtime pytest — collection потребує `aiogram`; частина DB-backed targeted tests потребує `aiosqlite`;
- PostgreSQL 18 integration;
- schema drift;
- backup capture/restore verification;
- Heroku deploy/health.

Ці перевірки залишаються blocking у локальному `.venv`/GitHub Actions.

## Manual QA перед tag
Обов’язково перевірити Dashboard, Мій кабінет, participant, events/event detail, ideas/idea detail, quests, badges, rewards, Security Center, Media Integrity, Help Center, notifications, reports і settings на 320/375/390/768/1024/1280/1440/1920 px.

Особливо: tabs не скролять сторінку; modal ESC/focus return; avatar не зміщує layout; sidebar logo стабільний; account dropdown; combobox; dark/light contrast; no horizontal overflow.
