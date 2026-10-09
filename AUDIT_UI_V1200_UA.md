# AMP XP v1.20.0 — UI/UX audit baseline

Аудит проведено перед рефакторингом **AMP XP v1.20.0 — Design System & Accessibility 2.0** на production-базі v1.19.1.

## Обсяг
Проаналізовано 64 Jinja templates, 56 з яких використовують `base.html`; окремими залишаються login/2FA/passkey, public event/opportunity та Telegram scanner surfaces. У шаблонах є 175 форм, 42 таблиці, 21 inline-style occurrence та 25 script blocks. Production CSS до рефакторингу мав 3695 рядків, 168 унікальних hex-кольорів, 2837 px literals, 793 `!important` та 122 media queries.

## Ключові проблеми baseline
1. **App shell**: desktop sidebar був постійно розгорнутий; desktop collapse/persistence не було. Mobile drawer відкривався, але не мав повного focus trap і гарантованого повернення focus.
2. **CSP/frontend architecture**: у `base.html` був великий inline JavaScript та inline `onclick`; це ускладнювало CSP hardening і тестування поведінки.
3. **Navigation**: навігація функціонально permission-aware, але мала багато однаково вагомих пунктів та emoji як іконки. Візуальна ієрархія була слабшою за інформаційну складність системи.
4. **CSS architecture**: один великий stylesheet змішував tokens, base, layout, component styles, hotfixes і page-specific overrides. Велика кількість hardcoded colors/spacing та `!important` свідчила про накопичений style debt.
5. **Design tokens**: базові змінні існували, але не покривали повноцінно semantic colors, spacing scale, typography, radii, focus, app-shell dimensions.
6. **Accessibility**: focus styles існували фрагментарно; не було skip-link; mobile drawer не мав повного keyboard trap; collapsed navigation була відсутня; system color preference не використовувався як початковий theme fallback.
7. **Tables**: більшість таблиць уже мали `.table-wrap`, але не всі surfaces мали однаковий responsive containment.
8. **Forms**: більшість полів мають labels і server/client validation, але загальний visual language полів, validation та touch targets був не повністю уніфікований.
9. **Cards/KPI/status**: багато сторінок використовують спільні класи, але historical overrides створили різні візуальні варіанти однакових сутностей.
10. **Login/security/media**: безпека була функціонально сильною, але UI login/2FA/passkey, Security Center і Media Integrity Center потребували більш чіткої hierarchy й сучаснішого presentation.

## Що збережено як production-вимога
- усі existing routes і bookmarks;
- backend permission checks;
- CSRF, 2FA, WebAuthn/passkeys, CSP nonce architecture;
- XP/attendance/QR/quests/rewards/gamification semantics;
- media privacy/lifecycle;
- audit trail;
- PostgreSQL/Alembic ownership;
- backup restore verification;
- privacy suppression;
- server-rendered FastAPI/Jinja architecture.

## Рішення v1.20.0
- sidebar: expanded / collapsed / mobile drawer;
- desktop preference у `localStorage`, без server dependency;
- mobile focus trap, ESC close, click-outside close, focus return, body scroll lock, ARIA state;
- один SVG icon system для app shell/navigation;
- modular design sources: `tokens.css`, `base.css`, `layout.css`, `components.css`, `utilities.css`;
- production bundle `admin.css`, що збирається детерміновано через `scripts/build_admin_css.py`; legacy compatibility CSS лишено як окремий шар, щоб не ламати historical pages;
- skip-link, global `:focus-visible`, reduced motion, semantic theme tokens;
- responsive shell від 320px;
- unified cards, buttons, fields, tables, alerts, status chips, auth surfaces;
- responsive table containment через progressive JS wrapper без зміни table semantics;
- modernized Security Center, Media Integrity Center та auth pages;
- dark/light/system architecture без зміни business logic.

## Свідомі межі релізу
v1.20.0 не переписує кожен historical template на нову компонентну markup-модель за один реліз. Старі класи залишені сумісними, а новий design layer перекриває їх системно. Це зменшує ризик regression у 64 templates і дозволяє мігрувати page-specific markup поступово без SPA rewrite.
