# AMP XP v1.20.0 — Accessibility

Target: **WCAG 2.2 AA** for the web administration shell and authentication flows.

Implemented:
- skip link to `#main-content`;
- semantic navigation landmarks and labels;
- visible `:focus-visible` ring using a dedicated focus token;
- keyboard-operable sidebar controls;
- mobile drawer focus trap;
- ESC close and click-outside close;
- focus return to hamburger after close;
- `aria-controls` / `aria-expanded` state;
- active navigation `aria-current="page"`;
- body scroll lock while drawer is open;
- reduced motion support;
- responsive touch targets around 40–46px for core controls;
- explicit labels on login/OTP fields;
- OTP help via `aria-describedby`;
- alerts use `role="alert"` / `role="status"` where relevant;
- responsive table regions remain native tables and become keyboard-scrollable when a wrapper is required;
- theme defaults to stored choice, otherwise system preference.

Manual verification remains required for color contrast, VoiceOver/NVDA navigation, zoom 200%, iOS/Android touch behavior and all page-specific dialogs/forms listed in `UI_VISUAL_CHECKLIST_V1200.md`.
