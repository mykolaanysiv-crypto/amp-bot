# AMP XP v1.20.1 — Accessibility Notes

Target: **WCAG 2.2 AA** where applicable to the server-rendered admin web UI.

## Preserved from v1.20.0

- skip link;
- semantic `main`/navigation landmarks;
- visible `:focus-visible` states;
- keyboard-operable sidebar/mobile drawer;
- focus return after mobile drawer;
- ARIA state for navigation controls;
- `prefers-reduced-motion`;
- labeled login/OTP/passkey controls.

## v1.20.1 additions

- native `<dialog>` for modal editing/confirmation;
- focus return to dialog opener;
- semantic close buttons with `aria-label`;
- responsive modal max width/height;
- no reliance on animation to communicate state;
- Help Center remains readable/searchable without JS;
- profile inputs keep visible labels and server validation;
- avatar upload is an explicit form, not drag-only interaction;
- action rows wrap rather than clip at narrow widths.

## Progressive enhancement

Legacy edit `<details>` remains functional in raw server HTML. `experience.js` converts eligible edit blocks to dialogs only after load. This prevents a JS failure from removing the ability to edit.

## Manual QA required

Automated source checks cannot prove final WCAG conformance. Before tagging verify keyboard-only navigation, browser zoom, 320px width, 200% zoom, VoiceOver/NVDA smoke where available, color contrast, focus visibility, dialog Esc/focus return and reduced-motion behavior.
