from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.model_domains import Event
from app.observability import JsonLogFormatter, log_extra
from app.reporting import resolve_report_period, resolve_report_storage_bounds
from app.domain_services import events as events_module
from app.time_utils import Clock


UTC = timezone.utc


def test_clock_is_aware_utc_and_kyiv_dst_safe():
    clock = Clock("Europe/Kyiv")
    now = clock.now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)

    # Local midnight maps to different UTC offsets in winter/summer.
    assert clock.local_wall_to_utc(datetime(2026, 1, 15, 0, 0)) == datetime(2026, 1, 14, 22, 0, tzinfo=UTC)
    assert clock.local_wall_to_utc(datetime(2026, 7, 15, 0, 0)) == datetime(2026, 7, 14, 21, 0, tzinfo=UTC)

    # 03:30 occurs twice when Europe/Kyiv falls back in October 2026.
    first = clock.local_wall_to_utc(datetime(2026, 10, 25, 3, 30), fold=0)
    second = clock.local_wall_to_utc(datetime(2026, 10, 25, 3, 30), fold=1)
    assert second - first == timedelta(hours=1)


def test_scheduler_local_target_uses_absolute_utc_across_spring_dst():
    clock = Clock("Europe/Kyiv")
    # 2026-03-29 00:30 UTC == 02:30 local, before the spring-forward jump.
    # 09:00 local that day == 06:00 UTC, so the real wait is 5h30m, not 6h30m.
    seconds = clock.seconds_until_local(
        hour=9,
        now_utc=datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
    )
    assert seconds == 5.5 * 3600


def test_local_report_midnight_boundary_converts_to_utc():
    clock = Clock("Europe/Kyiv")
    start, end, _ = resolve_report_period("month", year=2026, month=10)
    start_utc, end_utc = clock.local_period_to_storage_utc(start, end)
    assert start_utc == datetime(2026, 9, 30, 21, 0)
    assert end_utc == datetime(2026, 10, 31, 22, 0)  # October includes the DST fall-back.


async def test_checkin_window_uses_aware_utc_across_dst(monkeypatch):
    async def fake_runtime_int(_session, key: str) -> int:
        return {
            "events.checkin_open_before_minutes": 60,
            "events.checkin_close_after_minutes": 360,
        }[key]

    monkeypatch.setattr(events_module, "get_runtime_int", fake_runtime_int)
    event = Event(
        title="DST подія",
        description="",
        starts_at=datetime(2026, 10, 25, 3, 30),  # first 03:30 (fold=0)
        location="АМП",
        xp_reward=10,
        volunteer_hours=0,
        status="open",
        checkin_token="dst-checkin-token",
        share_token="dst-share-token",
    )

    opens = await events_module.event_checkin_window(
        object(),
        event,
        now=datetime(2026, 10, 24, 23, 30, tzinfo=UTC),
    )
    assert opens["state"] == "open"
    assert opens["opens_at_utc"] == datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
    assert opens["closes_at_utc"] == datetime(2026, 10, 25, 6, 30, tzinfo=UTC)
    # Six real hours after the event is 08:30 local because the offset changes.
    assert opens["closes_at"] == datetime(2026, 10, 25, 8, 30)

    closed = await events_module.event_checkin_window(
        object(),
        event,
        now=datetime(2026, 10, 25, 6, 30, 1, tzinfo=UTC),
    )
    assert closed["state"] == "closed"


def test_reports_use_utc_storage_bounds_for_local_calendar_periods():
    sep_start, sep_end, _ = resolve_report_period("month", year=2026, month=9)
    sep_start_utc, sep_end_utc = resolve_report_storage_bounds(sep_start, sep_end)
    assert sep_start_utc == datetime(2026, 8, 31, 21, 0)
    assert sep_end_utc == datetime(2026, 9, 30, 21, 0)

    oct_start, oct_end, _ = resolve_report_period("month", year=2026, month=10)
    oct_start_utc, oct_end_utc = resolve_report_storage_bounds(oct_start, oct_end)
    assert oct_start_utc == datetime(2026, 9, 30, 21, 0)
    assert oct_end_utc == datetime(2026, 10, 31, 22, 0)  # DST fallback changes offset.


def test_structured_logs_include_error_code_and_context():
    formatter = JsonLogFormatter("test")
    record = logging.LogRecord(
        name="amp.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="scheduler failed",
        args=(),
        exc_info=None,
    )
    extra = log_extra("SCHED_TEST_FAILED", scheduler="test_scheduler", token="must-not-leak")
    record.error_code = extra["error_code"]
    record.context = extra["context"]
    payload = json.loads(formatter.format(record))
    assert payload["error_code"] == "SCHED_TEST_FAILED"
    assert payload["context"]["scheduler"] == "test_scheduler"
    assert payload["context"]["token"] == "[REDACTED]"


def test_source_has_no_silent_broad_exception_or_direct_wall_clock_calls():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    direct_time = []
    silent_broad = []
    canonical = root / "app" / "time_utils.py"
    for scan_root in (root / "app", root / "scripts"):
        for path in scan_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if path != canonical and path.name != "production_preflight.py":
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        if (node.value.id, node.attr) in {
                            ("datetime", "utcnow"),
                            ("datetime", "now"),
                            ("date", "today"),
                        }:
                            direct_time.append(f"{path.relative_to(root)}:{node.lineno}")
                if isinstance(node, ast.ExceptHandler):
                    broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                    if broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        silent_broad.append(f"{path.relative_to(root)}:{node.lineno}")
    assert direct_time == []
    assert silent_broad == []


def test_orm_timestamp_defaults_use_zero_argument_clock_adapter():
    import inspect
    from app.model_domains import ContentView, User

    for model, column in ((User, "created_at"), (ContentView, "first_viewed_at")):
        default = model.__table__.c[column].default
        assert default is not None
        assert len(inspect.signature(default.arg).parameters) == 0
        value = default.arg(None)  # SQLAlchemy passes an execution context to wrapped defaults
        assert value.tzinfo is None  # legacy DB storage boundary remains naive UTC
