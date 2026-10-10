# AMP XP v1.20.3 — Accessibility

Target: WCAG 2.2 AA.

- No word-by-letter wrapping in buttons/tabs/chips.
- Focus behavior from previous releases retained.
- SVG icons are decorative where text already provides the accessible name.
- Tables remain keyboard-scrollable containers on narrow viewports.
- Modals remain native `<dialog>` based and constrained to mobile viewport.
- `prefers-reduced-motion: reduce` disables reveal and hover motion.
- Text/background semantic color tokens remain the source of truth for contrast.
