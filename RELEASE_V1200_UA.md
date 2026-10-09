# AMP XP v1.20.0 — Design System & Accessibility 2.0

v1.20.0 — великий UI/UX реліз без зміни доменної логіки. Він переводить AMP XP на новий app shell, design tokens, доступнішу navigation architecture та системний visual language.

## Основні зміни
- Новий desktop sidebar з режимами expanded/collapsed.
- Стан sidebar зберігається локально між сторінками.
- Mobile hamburger відкриває accessible drawer з backdrop, ESC, focus trap, focus return і body scroll lock.
- Core navigation перейшла з emoji на єдиний inline SVG icon system.
- Новий topbar: sidebar toggle, contextual title, global search, theme, attention, account.
- Design system: semantic colors, spacing, radius, typography, focus і app-shell tokens.
- CSS розділено на modular source files; `admin.css` збирається детерміновано.
- Legacy CSS винесено в compatibility layer, щоб не ламати historical templates.
- Єдиний modern style для cards, KPI, buttons, forms, tables, status chips, alerts, auth surfaces.
- Skip-link, `:focus-visible`, WCAG-oriented keyboard behavior і `prefers-reduced-motion`.
- Responsive layout від 320px; tables отримують safe internal scrolling без зміни native table semantics.
- Login, Telegram OTP, passkey UI, Security Center і Media Integrity Center оновлено в новій visual language.
- Light/dark/system theme architecture збережена і покращена.

## Що свідомо не змінювалося
XP, attendance, QR, quest completion, wallet, badges, rewards, seasons, leagues, surveys, notifications, permissions, 2FA, WebAuthn, media lifecycle, privacy suppression, audit, backups та route semantics.

## Database
Schema migration у v1.20.0 **не потрібна**. Alembic head залишається `20261008_0017`.

## Backward compatibility
Existing URLs і backend permission checks збережені. Jinja/FastAPI server-rendered architecture збережена; SPA/React/Vue rewrite не виконувався.

## Intentional regression-test updates
Historical UI source tests оновлено тільки там, де production-вимога свідомо змінилася: sidebar тепер використовує Jinja navigation macro + SVG icons замість literal href/emoji markup; inline `onclick` замінено CSP-safe event listeners; Media Integrity Center отримав зрозумілі українські назви замість технічних English labels. Security/permission/business invariants не послаблювалися.

## Відомі обмеження та compatibility debt
- Новий app shell не використовує inline `onclick` і підключає поведінку через nonce-compatible external JavaScript. Водночас у частині historical page-specific templates ще залишаються старі inline handlers; v1.20.0 їх не розширює і **не послаблює CSP** заради редизайну. Їх варто прибирати поступово окремими regression-safe змінами.
- `legacy.css` свідомо залишено compatibility layer: нова token/component система накладається поверх нього, щоб не переписувати всі historical templates одним ризиковим релізом.
- Реальні VoiceOver/NVDA, 200% zoom, iOS/Android та visual screenshot checks залишаються manual acceptance gates перед тегом.

## Manual QA
Див. `UI_VISUAL_CHECKLIST_V1200.md` та `ACCESSIBILITY_V1200.md`.

## Deployment
Release candidate можна merge лише після dependency/release consistency, compile, preflight, Ruff, JS smoke, pip-audit, full non-integration tests, PostgreSQL integration, schema drift, backup restore verification і post-deploy health/version checks.

## Rollback
UI release не має schema migration, тому preferred rollback — Heroku/GitHub application release rollback на попередній tested v1.19.1 commit. Дані та Alembic head залишаються `20261008_0017`.
