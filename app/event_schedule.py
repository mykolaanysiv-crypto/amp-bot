from __future__ import annotations

from datetime import timedelta

from .time_utils import clock


def event_end_local(event):
    """Return the event-local wall end time.

    Historical rows created before v1.17.2.4 do not have an explicit end time;
    they receive a conservative two-hour fallback until edited in the web UI.
    """
    return getattr(event, "ends_at", None) or (event.starts_at + timedelta(hours=2))


def event_end_utc(event):
    return clock.event_utc(event_end_local(event))
