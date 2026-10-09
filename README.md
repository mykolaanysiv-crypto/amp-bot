# AMP XP / «АМПасадори» v1.20.0

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Design System & Accessibility 2.0**. v1.20.0 modernizes the entire web shell and common component layer while preserving existing routes, permissions and domain semantics.

## Runtime
- Python 3.13
- Aiogram 3.31.0
- FastAPI + Jinja2 server-rendered web UI
- SQLAlchemy async
- PostgreSQL 18 baseline for CI/local/restore verification
- Alembic head: `20261008_0017`

## Design System & Accessibility 2.0
- desktop sidebar: expanded / collapsed;
- persisted sidebar preference via localStorage;
- accessible mobile drawer: backdrop, ESC, focus trap, focus return, body scroll lock;
- one inline SVG icon system for app-shell navigation;
- semantic design tokens for brand, surfaces, text, status, focus, spacing, typography and radii;
- modular CSS source with deterministic `admin.css` bundle;
- skip-link, global focus-visible styling and reduced-motion support;
- responsive shell down to 320px;
- unified cards, KPI, buttons, fields, tables, status chips, alerts and auth surfaces;
- modernized login/OTP/passkey, Security Center and Media Integrity Center;
- light/dark/system theme architecture.

## Security & data guarantees
v1.20.0 does not weaken CSRF, CSP, permission checks, 2FA, WebAuthn, privacy suppression, audit trail, media lifecycle, dependency audit, backup restore verification or schema drift gates.

## Media Storage & Data Lifecycle
v1.19.1 functionality remains intact: `MediaStorage` abstraction, DB/local/S3-compatible backends, checksum/MIME/size validation, integrity detection, quarantine-first lifecycle and database→S3 dry-run/copy/verify/switch/rollback tooling. No production media migration happens automatically.

## Database
v1.20.0 adds **no schema migration**. Current Alembic head remains:

```text
20261008_0017
```

## UI source architecture
- `app/web/static/legacy.css` — v1.19.1 compatibility layer;
- `tokens.css`, `base.css`, `layout.css`, `components.css`, `utilities.css` — v1.20.0 modular design sources;
- `scripts/build_admin_css.py` — deterministic production bundle builder;
- `app/web/static/app_shell.js` — sidebar, theme, mobile navigation, accessibility and progressive enhancements;
- `app/web/templates/_ui_macros.html` — shared SVG icon/navigation macros.

See `RELEASE_V1200_UA.md`, `AUDIT_UI_V1200_UA.md`, `DESIGN_SYSTEM_V1200.md`, `ACCESSIBILITY_V1200.md`, `UI_VISUAL_CHECKLIST_V1200.md`, `BUILD_MANIFEST_V1200.txt`, `TEST_REPORT_V1200.txt`, `COMMANDS_V1200.txt` and `HEROKU_DEPLOY.md`.

A ZIP or local test result is not proof of production. v1.20.0 becomes production only after green GitHub gates, restore-verified backup, successful Heroku release, health/version verification and manual critical-page visual QA.
