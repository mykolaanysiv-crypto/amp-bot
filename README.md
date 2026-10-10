# AMP XP / «АМПасадори» v1.20.3.1

Production-oriented Telegram + FastAPI + PostgreSQL system for the AMP participant programme.

Current release: **UI/UX Fix + Design Polish**. v1.20.3.1 is a focused patch over v1.20.3 that fixes broken word wrapping, severity-card color leakage, oversized shadows/modals, duplicate sidebar controls, transient notification UX and overview icon semantics without changing domain behavior.

## Runtime
- Python 3.13
- Aiogram 3.31.0
- FastAPI + Jinja2 server-rendered web UI
- SQLAlchemy async
- PostgreSQL 18 baseline for CI/local/restore verification
- Alembic head: `20261010_0018`
- **No new database migration in v1.20.3.1**

## Interaction architecture
- `app/web/static/app_shell.js` — shell/sidebar/mobile/theme behavior;
- `app/web/static/experience.js` — dialog/edit-flow/help progressive enhancement;
- `app/web/static/interaction.js` — semantic tabs, account dropdown, participant combobox and avatar preview;
- `app/web/static/polish.js` — compact transient toasts and empty-editor safety;
- `polish.css` — final no-word-splitting, shadows, modal centering, operations and toast policy;
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
v1.20.3.1 does not weaken CSRF, CSP, permission checks, 2FA, WebAuthn, privacy suppression, audit trail, media lifecycle, dependency audit, backup restore verification or schema drift gates.

## Database
Current Alembic head remains `20261010_0018` from v1.20.1 web profiles. A v1.20.3.1 code rollback therefore does not require a schema downgrade.

See `RELEASE_V12031_UA.md`, `AUDIT_UI_V12031_UA.md`, `DESIGN_SYSTEM_V12031.md`, `INTERACTION_SYSTEM_V12031.md`, `ACCESSIBILITY_V12031.md`, `UI_VISUAL_CHECKLIST_V12031.md`, `BUILD_MANIFEST_V12031.txt`, `TEST_REPORT_V12031.txt`, `COMMANDS_V12031.txt` and `HEROKU_DEPLOY.md`.

A ZIP or local test result is not proof of production. v1.20.3.1 becomes production only after green GitHub gates, restore-verified backup, successful Heroku release, health/version verification and manual critical-page visual QA.
