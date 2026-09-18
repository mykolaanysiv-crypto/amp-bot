from __future__ import annotations

from datetime import datetime, timedelta

from .time_utils import clock


def deadline_urgency(item, now_utc=None) -> dict[str, object]:
    now_utc = now_utc or clock.now_utc()
    if not getattr(item, "active", False):
        return {"urgent": False, "expired": False, "remaining": None}
    deadline = getattr(item, "deadline", None)
    if not deadline:
        return {"urgent": False, "expired": False, "remaining": None}
    deadline_utc = clock.local_wall_to_utc(deadline)
    remaining = deadline_utc - now_utc
    expired = remaining.total_seconds() < 0
    urgent = (not expired) and remaining <= timedelta(days=3)
    return {"urgent": urgent, "expired": expired, "remaining": remaining}


def opportunity_sort_key(item, now_utc=None):
    """Canonical automatic ordering: current first, nearest deadline first.

    Active opportunities with a deadline come first by nearest deadline. Active
    opportunities without a deadline follow by newest arrival. Inactive/expired
    opportunities are pushed to the bottom and ordered by newest arrival.
    """
    now_utc = now_utc or clock.now_utc()
    state = deadline_urgency(item, now_utc)
    effective_active = bool(getattr(item, "active", False)) and not state["expired"]
    created = getattr(item, "created_at", None) or datetime.min
    deadline = getattr(item, "deadline", None)
    created_ts = created.timestamp() if created != datetime.min else 0.0
    if effective_active and deadline:
        return (0, 0, deadline, -created_ts)
    if effective_active:
        return (0, 1, datetime.max, -created_ts)
    return (1, 0, datetime.max, -created_ts)
