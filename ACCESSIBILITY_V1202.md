# AMP XP v1.20.2 — Accessibility

Ціль: **WCAG 2.2 AA** для основних application flows.

## Реалізовано
- semantic tab roles + `aria-selected`, `aria-controls`, `aria-labelledby`;
- keyboard tabs: arrows/Home/End;
- focus without unexpected scrolling;
- dialog ESC/focus behavior inherited from the accessible modal layer;
- account dropdown `aria-expanded` and keyboard close;
- participant combobox/listbox semantics;
- toast `role=status` / live feedback;
- stable square avatar dimensions with meaningful surrounding text;
- visible focus states;
- stronger muted/placeholder/gradient contrast;
- reduced-motion fallback;
- mobile dialogs constrained to viewport height.

## Manual checks still required
Screen reader pass, contrast inspection in both themes, keyboard-only walkthrough, 200% zoom, 320px viewport, long-name/avatar cases and destructive-dialog semantics must be verified before tag.
