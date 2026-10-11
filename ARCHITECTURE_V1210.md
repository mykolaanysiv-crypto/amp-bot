AMP XP v1.22.0 — retains historical v1.21.0 evidence and baseline.
# Architecture — AMP XP v1.21.0

## UI layers
1. Product workspace — everyday modules.
2. Management workspace — staff/admin operations.
3. System workspace — protected system/security/integrity tools.

`app/web/dependencies.py::ctx()` exposes role-aware presentation flags:
- `is_management_ui`
- `is_participant_ui`
- `is_system_ui`

These flags affect presentation only. `has_web_permission()` and route guards remain the authorization source of truth.

## Existing modules
Not shown in mockup ≠ remove from product. Protected routes such as Security Center, Media Integrity, Operations, Audit, Permissions and Settings remain intact.

## Frontend architecture
FastAPI + Jinja2 + modular CSS + external JS. No SPA rewrite. No inline executable JS.

## Database
No schema change. Alembic head remains `20261010_0018`.


AMP XP v1.22.1 UI refinement candidate; see RELEASE_V1221_UA.md for scope and verification.
