# AMP XP v1.20.2 — Design System Addendum

v1.20.2 розширює Design System v1.20.x interaction-рівнем без заміни FastAPI/Jinja2 architecture.

## Interaction surfaces
- `.amp-tabs`, `.amp-tablist`, `.amp-tab`, `.amp-tab-indicator`, `.amp-tab-panel`;
- `.account-menu`;
- `.amp-modal` + avatar dialog/dropzone/danger zone;
- `.amp-toast-region`, `.amp-toast`;
- participant combobox/listbox;
- compact avatar/user identity surfaces;
- adaptive content containers and responsive grids.

## Motion tokens
```css
--motion-fast: 120ms;
--motion-base: 200ms;
--motion-slow: 320ms;
--ease-standard: ...;
--ease-emphasized: ...;
```

Motion використовується для пояснення зміни state: tabs, dialogs, hover elevation, account dropdown, toasts. `prefers-reduced-motion` вимикає/мінімізує неістотні transitions.

## Icon rule
System-authored web UI використовує один Jinja SVG macro `icon(...)` з узгодженим 24×24 viewBox/stroke. Emoji не використовуються як системні UI icons; user-generated та Telegram content не переписується.

## Layout rule
Не існує одного max-width для всіх сторінок. Text-heavy forms зберігають читабельну ширину, а dashboard/detail/analytics/card grids можуть використовувати ширший viewport.
