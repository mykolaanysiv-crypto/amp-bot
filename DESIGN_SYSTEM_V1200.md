# AMP XP v1.20.0 — Design System

## Напрямок
Modern civic-tech / SaaS: чистий, професійний, молодіжний, але не дитячий. Айдентика AMP зберігає бірюзово-teal основу; семантичні success/warning/danger/info кольори відділені від brand color.

## Tokens
Source: `app/web/static/tokens.css`.

- semantic colors: `--color-primary`, `--color-success`, `--color-warning`, `--color-danger`, `--color-info`;
- surfaces/text/borders/focus;
- spacing scale 4/8/12/16/20/24/32/40/48/64;
- radius scale sm/md/lg/xl/pill;
- typography scale caption → display;
- app shell dimensions `--sidebar-expanded`, `--sidebar-collapsed`, `--topbar-height`.

## CSS architecture
- `legacy.css` — frozen compatibility layer from v1.19.1;
- `tokens.css` — semantic values;
- `base.css` — reset, typography, focus, skip-link, reduced motion;
- `layout.css` — app shell/sidebar/topbar/responsive behavior;
- `components.css` — cards/buttons/forms/tables/status/auth/dialog/feedback patterns;
- `utilities.css` — small composition helpers;
- `admin.css` — generated production bundle.

Rebuild:

```bash
python -m scripts.build_admin_css
```

## App shell
Desktop has expanded/collapsed sidebar. Compact mode keeps icon navigation and `title` tooltip. Main content and topbar automatically resize. Mobile uses drawer/off-canvas navigation.

## Components
Primary / secondary-soft / danger / success actions; cards and KPI; semantic chips; inline validation; alert/status surfaces; table wrappers; auth cards; future dialog/toast primitives.

## Iconography
Core shell/navigation uses one inline SVG line-icon system from `_ui_macros.html`. Historical content emoji may remain only where they are existing domain copy, not as the primary navigation icon system.
