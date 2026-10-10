# AMP XP / «АМПасадори» v1.20.2

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **UI Polish, Navigation & Interaction 3.0**. v1.20.2 turns the v1.20.x visual redesign into a more coherent interactive product: real tabs, dialogs, unified SVG icons, stable account/sidebar identity, participant combobox, motion/toasts and stronger responsive/contrast behavior.

## Runtime
- Python 3.13
- Aiogram 3.31.0
- FastAPI + Jinja2 server-rendered web UI
- SQLAlchemy async
- PostgreSQL 18 baseline for CI/local/restore verification
- Alembic head: `20261010_0018`
- **No new database migration in v1.20.2**

## Interaction architecture
- `app/web/static/app_shell.js` — shell/sidebar/mobile/theme behavior;
- `app/web/static/experience.js` — dialog/edit-flow/help progressive enhancement;
- `app/web/static/interaction.js` — semantic tabs, account dropdown, participant combobox, avatar preview and toasts;
- `interaction.css` — motion, tabs, dialogs, account menu, combobox, toast and adaptive layout polish;
- `scripts/build_admin_css.py` — deterministic CSS bundle;
- `_ui_macros.html` — unified SVG icon/navigation macros.

## Key UX guarantees
- tabs are real panels, not same-page anchor scroll;
- system-authored web UI uses one SVG icon system rather than emoji;
- profile/avatar edit uses dialog flows;
- sidebar/logo/avatar geometry remains stable;
- participant linking is searchable and permission-checked;
- reduced-motion/accessibility behavior remains supported;
- existing backend URLs/forms/security/domain semantics remain intact.

## Security & data guarantees
v1.20.2 does not weaken CSRF, CSP, permission checks, 2FA, WebAuthn, privacy suppression, audit trail, media lifecycle, dependency audit, backup restore verification or schema drift gates.

## Database
Current Alembic head remains `20261010_0018` from v1.20.1 web profiles. A v1.20.2 code rollback therefore does not require a schema downgrade.

See `RELEASE_V1202_UA.md`, `AUDIT_UI_V1202_UA.md`, `DESIGN_SYSTEM_V1202.md`, `INTERACTION_SYSTEM_V1202.md`, `ACCESSIBILITY_V1202.md`, `UI_VISUAL_CHECKLIST_V1202.md`, `BUILD_MANIFEST_V1202.txt`, `TEST_REPORT_V1202.txt`, `COMMANDS_V1202.txt` and `HEROKU_DEPLOY.md`.

A ZIP or local test result is not proof of production. v1.20.2 becomes production only after green GitHub gates, restore-verified backup, successful Heroku release, health/version verification and manual critical-page visual QA.
