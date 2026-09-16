from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
DEFAULT_TIMEZONE = "Europe/Kyiv"


@dataclass(frozen=True, slots=True)
class Clock:
    """Single time boundary for AMP business logic.

    Business decisions use timezone-aware UTC.  The current database schema still
    contains legacy ``timestamp without time zone`` columns, so persistence
    adapters deliberately convert aware UTC to naive UTC and event wall-clock
    values to naive local time at the boundary.  This keeps production data
    compatible while preventing UTC/local comparisons inside business logic.
    """

    timezone_name: str | None = None

    @property
    def tz(self) -> ZoneInfo:
        name = (self.timezone_name or os.getenv("TIMEZONE") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            return ZoneInfo(DEFAULT_TIMEZONE)

    def now_utc(self) -> datetime:
        """Return an aware UTC timestamp."""
        return datetime.now(UTC)

    def now_local(self) -> datetime:
        """Return an aware timestamp in the configured community timezone."""
        return self.now_utc().astimezone(self.tz)

    def today_local(self) -> date:
        return self.now_local().date()

    def ensure_utc(self, value: datetime, *, assume_tz: ZoneInfo | timezone = UTC, fold: int = 0) -> datetime:
        """Normalize a datetime to aware UTC.

        Naive values are interpreted only at an explicit boundary.  ``fold`` is
        exposed for repeated wall-clock times during the autumn DST transition.
        """
        if value.tzinfo is None:
            value = value.replace(tzinfo=assume_tz, fold=fold)
        return value.astimezone(UTC)

    def local_wall_to_utc(self, value: datetime, *, fold: int = 0) -> datetime:
        """Interpret a naive event/report wall time in the configured timezone."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.tz, fold=fold)
        return value.astimezone(UTC)

    def utc_to_local(self, value: datetime) -> datetime:
        return self.ensure_utc(value).astimezone(self.tz)

    def local_wall(self, value: datetime | None = None) -> datetime:
        """Return a naive local wall-clock value for legacy event DB fields/UI."""
        source = value or self.now_utc()
        return self.utc_to_local(source).replace(tzinfo=None)

    def storage_utc(self, value: datetime | None = None) -> datetime:
        """Return naive UTC for legacy timestamp-without-time-zone DB columns."""
        source = value or self.now_utc()
        return self.ensure_utc(source).replace(tzinfo=None)

    def from_storage_utc(self, value: datetime | None) -> datetime | None:
        """Interpret a legacy naive DB timestamp as UTC and return aware UTC."""
        if value is None:
            return None
        return self.ensure_utc(value, assume_tz=UTC)

    def event_utc(self, value: datetime | None, *, fold: int = 0) -> datetime | None:
        """Convert Event.starts_at local-wall storage to aware UTC."""
        if value is None:
            return None
        return self.local_wall_to_utc(value, fold=fold)

    def local_period_to_storage_utc(self, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        """Convert local report boundaries to naive UTC DB boundaries.

        This is DST-safe: a local calendar day/month may contain 23 or 25 hours.
        """
        start_utc = self.local_wall_to_utc(start)
        end_utc = self.local_wall_to_utc(end)
        return self.storage_utc(start_utc), self.storage_utc(end_utc)

    def local_midnight_utc(self, day: date) -> datetime:
        return self.local_wall_to_utc(datetime.combine(day, time.min))

    def seconds_until_local(self, *, hour: int, minute: int = 0, now_utc: datetime | None = None) -> float:
        """Seconds until today's/next local wall-clock target, DST-safe."""
        current_utc = self.ensure_utc(now_utc or self.now_utc())
        current_local = current_utc.astimezone(self.tz)
        target_local = current_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_local <= current_local:
            target_local = datetime.combine(
                current_local.date() + timedelta(days=1),
                time(hour=hour, minute=minute),
                tzinfo=self.tz,
            )
        target_utc = target_local.astimezone(UTC)
        return max(0.0, (target_utc - current_utc).total_seconds())


clock = Clock()


# Compatibility wrappers. New business code should use ``clock`` directly.
def utc_now() -> datetime:
    return clock.now_utc()


def utc_storage_now() -> datetime:
    return clock.storage_utc()


def event_local_now() -> datetime:
    return clock.local_wall()
