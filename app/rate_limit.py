from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi.responses import JSONResponse, Response

from .security import client_ip


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


class SlidingWindowRateLimiter:
    """Process-local server-side limiter with bounded sliding windows.

    AMP currently runs a small explicit web dyno pool. This layer complements
    account lockout and permission checks; it does not replace them. Keys are
    privacy-minimized hashes in memory only and are never persisted.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._windows: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, rule: RateLimitRule) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - max(1, int(rule.window_seconds))
        async with self._lock:
            # Prevent unbounded cardinality growth without evicting active
            # security windows. A new key is rejected when memory is saturated;
            # existing keys continue to use their normal limits.
            if key not in self._events and len(self._events) >= 20_000:
                return False, max(1, int(rule.window_seconds))
            bucket = self._events[key]
            self._windows[key] = max(1, int(rule.window_seconds))
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= max(1, int(rule.limit)):
                retry_after = max(1, int(rule.window_seconds - (now - bucket[0]))) if bucket else rule.window_seconds
                return False, retry_after
            bucket.append(now)
            if len(self._events) > 10_000:
                # Clean a bounded slice using each key's own window. Never apply
                # a short QR window to a longer login/password-reset bucket.
                for old_key in list(self._events)[:2_000]:
                    q = self._events[old_key]
                    old_window = self._windows.get(old_key, 900)
                    old_cutoff = now - max(1, int(old_window))
                    while q and q[0] <= old_cutoff:
                        q.popleft()
                    if not q:
                        self._events.pop(old_key, None)
                        self._windows.pop(old_key, None)
            return True, 0


limiter = SlidingWindowRateLimiter()


def classify_rate_limit(path: str, method: str, content_type: str = "") -> RateLimitRule | None:
    method = (method or "GET").upper()
    path = path or "/"
    if method == "POST" and path == "/admin/login":
        return RateLimitRule("login", 10, 300)
    if method == "POST" and path in {"/admin/login/2fa", "/admin/login/passkey/verify", "/admin/login/passkey/fallback"}:
        return RateLimitRule("mfa", 12, 600)
    if path == "/admin/login/passkey/options":
        return RateLimitRule("passkey_options", 20, 600)
    if method == "POST" and path.startswith("/admin/account/passkeys"):
        return RateLimitRule("passkey_manage", 12, 600)
    if method == "POST" and "/reset-password" in path:
        return RateLimitRule("password_reset", 6, 900)
    if "scanner" in path or "checkin" in path:
        return RateLimitRule("qr", 180, 60)
    if path == "/admin/export/sensitive" or "participants-sensitive" in path:
        return RateLimitRule("sensitive_export", 8, 300)
    if method in {"POST", "PUT", "PATCH"} and "multipart/form-data" in (content_type or "").lower():
        return RateLimitRule("upload", 40, 300)
    if path.startswith("/event/") or path.startswith("/opportunity/"):
        return RateLimitRule("public_share", 120, 300)
    return None


class RateLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers_list = list(scope.get("headers") or [])
        headers = {k.lower(): v for k, v in headers_list}
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET")
        content_type = headers.get(b"content-type", b"").decode("latin1", "ignore")
        rule = classify_rate_limit(path, method, content_type)
        if rule is None:
            await self.app(scope, receive, send)
            return
        ip = client_ip(headers_list, (scope.get("client") or ("", 0))[0]) or "unknown"
        # Avoid retaining the raw address as an in-memory dictionary key.
        from hashlib import sha256
        subject = sha256(ip.encode("utf-8", "ignore")).hexdigest()[:20]
        allowed, retry_after = await limiter.hit(f"{rule.name}:{subject}", rule)
        if not allowed:
            body = {"detail": "Забагато запитів. Спробуйте пізніше.", "rate_limit": rule.name}
            response: Response
            if path.startswith("/admin") and "application/json" not in headers.get(b"accept", b"").decode("latin1", "ignore"):
                response = Response(
                    "<h1>429</h1><p>Забагато запитів. Спробуйте ще раз трохи пізніше.</p>",
                    status_code=429,
                    media_type="text/html",
                    headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
                )
            else:
                response = JSONResponse(body, status_code=429, headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
