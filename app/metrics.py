from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterable

_PATH_ID_RE = re.compile(r"/(?P<id>\d+)(?=/|$)")


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (len(ordered) - 1) * max(0.0, min(1.0, percentile))
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        value = ordered[low]
    else:
        value = ordered[low] + (ordered[high] - ordered[low]) * (rank - low)
    return round(value, 2)


def _normalized_path(path: str) -> str:
    text = (path or "/")[:500]
    return _PATH_ID_RE.sub("/:id", text)


@dataclass(frozen=True, slots=True)
class MetricSample:
    at_monotonic: float
    value_ms: float
    label: str
    status: int = 0


class RuntimeMetrics:
    """Small bounded in-process telemetry buffer.

    It contains only timing/counter metadata and never request bodies, query
    parameters, participant identifiers, Telegram ids, credentials or secrets.
    Persistent operational state continues to live in PostgreSQL.
    """

    def __init__(self, max_samples: int = 4096) -> None:
        self._lock = threading.Lock()
        self._http: deque[MetricSample] = deque(maxlen=max_samples)
        self._db: deque[MetricSample] = deque(maxlen=max_samples)
        self._telegram_failures: deque[float] = deque(maxlen=max_samples)

    def record_http(self, *, path: str, duration_ms: float, status: int) -> None:
        with self._lock:
            self._http.append(MetricSample(time.monotonic(), max(0.0, duration_ms), _normalized_path(path), int(status)))

    def record_db(self, *, duration_ms: float, label: str = "query") -> None:
        with self._lock:
            self._db.append(MetricSample(time.monotonic(), max(0.0, duration_ms), label[:80], 0))

    def record_telegram_failure(self) -> None:
        with self._lock:
            self._telegram_failures.append(time.monotonic())

    def snapshot(self, *, window_seconds: int = 900) -> dict[str, object]:
        now = time.monotonic()
        cutoff = now - max(60, int(window_seconds))
        with self._lock:
            http = [s for s in self._http if s.at_monotonic >= cutoff]
            db = [s for s in self._db if s.at_monotonic >= cutoff]
            telegram_failures = sum(1 for ts in self._telegram_failures if ts >= cutoff)

        http_values = [s.value_ms for s in http]
        db_values = [s.value_ms for s in db]
        export_values = [
            s.value_ms for s in http
            if "export" in s.label or s.label.endswith((".xlsx", ".pdf", ".png"))
        ]
        error_responses = sum(1 for s in http if s.status >= 500)
        return {
            "window_seconds": max(60, int(window_seconds)),
            "http": {
                "samples": len(http),
                "p50_ms": _percentile(http_values, 0.50),
                "p95_ms": _percentile(http_values, 0.95),
                "max_ms": round(max(http_values), 2) if http_values else None,
                "server_error_responses": error_responses,
            },
            "db": {
                "samples": len(db),
                "p50_ms": _percentile(db_values, 0.50),
                "p95_ms": _percentile(db_values, 0.95),
                "max_ms": round(max(db_values), 2) if db_values else None,
            },
            "exports": {
                "samples": len(export_values),
                "p50_ms": _percentile(export_values, 0.50),
                "p95_ms": _percentile(export_values, 0.95),
            },
            "telegram_api_failures": telegram_failures,
        }


runtime_metrics = RuntimeMetrics()
