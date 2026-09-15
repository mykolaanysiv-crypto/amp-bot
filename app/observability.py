from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterable

_request_id: ContextVar[str] = ContextVar("amp_request_id", default="")


class SensitiveDataFilter(logging.Filter):
    """Redact configured secrets from all log records before serialization."""

    SECRET_NAMES = (
        "BOT_TOKEN", "MONOBANK_TOKEN", "DATABASE_URL", "WEB_SESSION_SECRET",
        "SENTRY_DSN", "HEROKU_API_KEY",
    )

    def __init__(self) -> None:
        super().__init__()
        self._values = tuple(
            value for value in (os.getenv(name, "").strip() for name in self.SECRET_NAMES)
            if len(value) >= 6
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
            for value in self._values:
                rendered = rendered.replace(value, "[REDACTED]")
            # Telegram bot tokens have a characteristic numeric-prefix format.
            rendered = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", "[REDACTED_BOT_TOKEN]", rendered)
            record.msg = rendered
            record.args = ()
        except Exception:
            pass
        return True


class JsonLogFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = _request_id.get()
        if request_id:
            payload["request_id"] = request_id
        dyno = os.getenv("DYNO", "").strip()
        if dyno:
            payload["dyno"] = dyno
        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                "message": str(record.exc_info[1])[:1000] if record.exc_info[1] else "",
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_observability(*, service: str) -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveDataFilter())
    if os.getenv("LOG_FORMAT", "json" if os.getenv("DYNO") else "text").lower() == "json":
        handler.setFormatter(JsonLogFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
    _init_sentry(service=service)


def _init_sentry(*, service: str) -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("APP_ENV", "production" if os.getenv("DYNO") else "development"),
            release=os.getenv("APP_RELEASE", ""),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0") or 0.0),
            send_default_pii=False,
            before_send=_sentry_scrub,
        )
        sentry_sdk.set_tag("service", service)
    except Exception:
        logging.getLogger(__name__).exception("Не вдалося ініціалізувати Sentry")


def _sentry_scrub(event, hint):
    request = event.get("request") or {}
    if isinstance(request, dict):
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in {"authorization", "cookie", "x-token"}:
                    headers[key] = "[REDACTED]"
    user = event.get("user")
    if isinstance(user, dict):
        for key in ("email", "ip_address", "username"):
            user.pop(key, None)
    return event


def set_request_id(value: str | None = None):
    return _request_id.set(value or uuid.uuid4().hex[:16])


def reset_request_id(token) -> None:
    _request_id.reset(token)


class RequestContextMiddleware:
    """ASGI middleware adding a correlation id without storing request bodies."""

    def __init__(self, app, service: str = "web") -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        request_id = headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = set_request_id(request_id)

        async def send_with_id(message):
            if message.get("type") == "http.response.start":
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-request-id", request_id.encode("ascii", "ignore")))
                message["headers"] = raw_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset_request_id(token)
