# AMP v1.12.1.4 — Event Capacity Runtime Hotfix

Production worker logs exposed a refactor regression in `process_event_operations()`:
`EVENT_OCCUPIED_STATUSES` was referenced after being lost during the services split.
The canonical capacity-consuming states have been restored in the event domain:
`registered`, `reserved`, `checked_in`, `attended`.

No database schema, XP rules, user-facing UX, or runtime configuration changes.
