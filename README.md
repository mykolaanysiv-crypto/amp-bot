# AMP XP / «АМПасадори» v1.21.0

Current release: **Product Experience Redesign**.

v1.21.0 rebuilds the product-facing web experience around a youth-tech / civic-tech design system while preserving production domain behavior and role/permission boundaries. The release introduces a product-first dashboard, role-aware navigation layers, modern event/registration and ideas discovery workspaces, refreshed gamification presentation, softer motion and glass accents, and a consistent semantic SVG system.

## Architecture

- FastAPI + Jinja2 server-rendered web UI.
- Modular CSS/JS; no React/Vue rewrite.
- Permission checks remain server-side source of truth.
- Admin and superadmin tools remain available even when not represented in visual mockups.
- Participant-facing architecture is intentionally simpler and must not expose system/admin tools.
- No new database migration in v1.21.0.
- Alembic head remains `20261010_0018`.
- Python baseline: 3.13.
- PostgreSQL baseline: 18.

## Security and reliability

v1.21.0 does not weaken CSRF, CSP, 2FA, WebAuthn/passkeys, permissions, privacy suppression, audit trail, field encryption, media lifecycle, schema drift checks, pip-audit or restore-verified backup gates.

## Release status

A local ZIP or passing source test is not proof of production. v1.21.0 becomes production only after the blocking GitHub gates, PostgreSQL 18 integration/schema checks, restore-verified backup, successful Heroku release, health/version checks and manual visual QA.
