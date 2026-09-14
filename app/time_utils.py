from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def event_local_now() -> datetime:
    """Return naive wall-clock time in the timezone used by Event.starts_at.

    Event dates are entered/displayed as local wall-clock values and stored as
    naive datetimes. Heroku itself normally runs in UTC, so datetime.utcnow()
    cannot be compared directly with Event.starts_at without shifting the
    operational check-in window. Keep this helper deliberately event-specific;
    audit/created_at timestamps elsewhere can remain on their existing clock.
    """
    name = (os.getenv("TIMEZONE") or "Europe/Kyiv").strip() or "Europe/Kyiv"
    try:
        tz = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Europe/Kyiv")
    return datetime.now(tz).replace(tzinfo=None)
