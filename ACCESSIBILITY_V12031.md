# Accessibility v1.20.3.1

Target: WCAG 2.2 AA.

- Words are not broken into unreadable fragments.
- Focus semantics from v1.20.x are retained.
- Toasts use live-region compatible status/alert roles and have explicit close labels.
- Modal dialogs stay centered inside the viewport and retain native `<dialog>` keyboard behavior.
- Icon-only controls keep `aria-label`.
- Reduced motion remains supported.
- Color is not the only OperationalIssue severity signal: text badge + border remain visible.
