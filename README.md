# AMP XP / «АМПасадори» v1.20.1

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **Visual Experience & User Profiles**. v1.20.1 deepens the v1.20.0 design system across internal content, dialogs, Help Center and the web user cabinet while preserving routes, permissions and domain semantics.

## Runtime
- Python 3.13
- Aiogram 3.31.0
- FastAPI + Jinja2 server-rendered web UI
- SQLAlchemy async
- PostgreSQL 18 baseline for CI/local/restore verification
- Alembic head: `20261010_0018`

## Visual Experience & User Profiles
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
v1.20.1 does not weaken CSRF, CSP, permission checks, 2FA, WebAuthn, privacy suppression, audit trail, media lifecycle, dependency audit, backup restore verification or schema drift gates.

## Media Storage & Data Lifecycle
v1.19.1 functionality remains intact: `MediaStorage` abstraction, DB/local/S3-compatible backends, checksum/MIME/size validation, integrity detection, quarantine-first lifecycle and database→S3 dry-run/copy/verify/switch/rollback tooling. No production media migration happens automatically.

## Database
v1.20.1 adds one additive web-profile migration. Current Alembic head:

```text
20261010_0018
```

The migration adds optional profile metadata/avatar reference and an optional link from a web staff account to an existing AMP participant profile. It does not change XP, attendance, quests, rewards or media lifecycle semantics.

## UI source architecture
- `app/web/static/legacy.css` — v1.19.1 compatibility layer;
- `tokens.css`, `base.css`, `layout.css`, `components.css`, `experience.css`, `utilities.css` — v1.20.1 modular design sources;
- `scripts/build_admin_css.py` — deterministic production bundle builder;
- `app/web/static/app_shell.js` — sidebar, theme, mobile navigation and accessibility;
- `app/web/static/experience.js` — dialogs, safe confirmations, Help Center search and progressive edit-flow enhancement;
- `app/web/templates/_ui_macros.html` — shared SVG icon/navigation macros.

See `RELEASE_V1201_UA.md`, `AUDIT_UI_V1201_UA.md`, `DESIGN_SYSTEM_V1201.md`, `ACCESSIBILITY_V1201.md`, `UI_VISUAL_CHECKLIST_V1201.md`, `BUILD_MANIFEST_V1201.txt`, `TEST_REPORT_V1201.txt`, `COMMANDS_V1201.txt` and `HEROKU_DEPLOY.md`.

A ZIP or local test result is not proof of production. v1.20.1 becomes production only after green GitHub gates, restore-verified backup, successful Heroku release, health/version verification and manual critical-page visual QA.
