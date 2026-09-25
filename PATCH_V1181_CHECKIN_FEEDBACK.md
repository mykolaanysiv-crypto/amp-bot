# v1.18.1: check-in test and manual feedback resend correction

- `tests/test_v1103_data_integrity.py`: update inclusive closing-boundary expectation to `event.ends_at + 60 minutes`, matching v1.17.2.4 event schedule semantics (and leaving the inclusive `>` comparison in `event_checkin_window` unchanged). Existing events default to two hours duration; their standard check-in closes one hour later.
- `app/web/event_routes/mutations.py`: manual feedback resend now selects **confirmed** `attended` registrations only; excludes unchecked/unconfirmed `checked_in` registrations and completed feedback. Active users with Telegram IDs continue to be required. The automatic feedback job remains unchanged.
- `app/web/event_routes/overview.py`: pending manual-resend count uses the same confirmed-attendee eligibility rule.
- `tests/test_v11703_event_feedback_resend.py`: assert confirmed-attendee-only filter and matching count.

No schema migration. VERSION.txt remains 1.18.1. This is a corrected artifact, not evidence of deployment. Run full `pytest`, CI PostgreSQL smoke, and backup verification before any production deployment.
