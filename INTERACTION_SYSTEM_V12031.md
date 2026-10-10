# Interaction System v1.20.3.1

## Toasts
`window.AMPToast.show(message, type, timeout)` is the single transient notification API.
- location: bottom-left of content area;
- types: success/error/warning/info;
- compact semantic SVG icon;
- close button;
- auto-dismiss;
- `role=status` / `role=alert` as appropriate.

Only explicit `data-toast-source` alerts are converted. Persistent warnings remain in the page.

## Dialogs
Dialogs are fixed/centered and constrained to standard/editor/wide sizes. Empty generated editor dialogs are blocked and replaced by a small informational toast.

## Sidebar
Desktop collapse/expand remains controlled from the sidebar header. The duplicate topbar control is removed.
