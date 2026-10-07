from __future__ import annotations

from ..time_utils import clock

from datetime import datetime, timedelta
import secrets
from hmac import compare_digest

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from ..model_domains import WebAdminSession, WebStaffAccount
from ..security import token_hash
from ..permissions import effective_permissions, required_web_permission, required_web_any_permissions


class CSRFMiddleware:
    """Require a per-session CSRF token for every unsafe /admin request.

    The body is replayed after validation, so ordinary FastAPI Form/File
    parameters continue to work unchanged.
    """

    def __init__(self, app, *, max_body_bytes: int = 25 * 1024 * 1024):
        self.app = app
        self.max_body_bytes = max(1024, int(max_body_bytes))

    async def _reject_too_large(self, scope, receive, send) -> None:
        response = HTMLResponse(
            "<h1>413</h1><p>Запит завеликий. Максимальний розмір форми перевищено.</p>",
            status_code=413,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        if not path.startswith("/admin") or method not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return

        # v1.18.6: reject oversized admin requests before Starlette multipart
        # parsing and before CSRF buffering. Per-file validation still enforces
        # the stricter 20 MiB upload limit in dependencies.py.
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        raw_length = headers.get(b"content-length", b"").decode("ascii", "ignore").strip()
        if raw_length.isdigit() and int(raw_length) > self.max_body_bytes:
            await self._reject_too_large(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                await self._reject_too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        raw = bytes(body)
        used = False

        async def replay_receive():
            nonlocal used
            if not used:
                used = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        session = scope.get("session") or {}
        expected = str(session.get("csrf_token") or "")
        try:
            request = Request(scope, receive=replay_receive)
            form = await request.form()
            submitted = str(form.get("_csrf") or "")
        except Exception:
            submitted = ""

        if not expected or not submitted or not compare_digest(expected, submitted):
            response = HTMLResponse(
                "<h1>403</h1><p>Захисний токен форми недійсний або застарів. Оновіть сторінку та повторіть дію.</p>",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        # New replay for downstream because the parser above consumed its copy.
        downstream_used = False

        async def downstream_receive():
            nonlocal downstream_used
            if not downstream_used:
                downstream_used = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, downstream_receive, send)


class AdminSessionValidationMiddleware:
    """Validate server-side web sessions before protected admin requests."""

    def __init__(self, app, db):
        self.app = app
        self.db = db

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if not path.startswith("/admin") or path in {"/admin/login", "/admin/login/2fa"}:
            await self.app(scope, receive, send)
            return

        session_cookie = scope.get("session") or {}
        if not session_cookie.get("admin_auth"):
            await self.app(scope, receive, send)
            return

        raw_token = str(session_cookie.get("admin_session_token") or "")
        if not raw_token:
            session_cookie.clear()
            response = RedirectResponse("/admin/login", status_code=303)
            await response(scope, receive, send)
            return

        now = clock.storage_utc()
        valid = False
        account = None
        server_session = None
        async with self.db.session_factory() as dbs:
            server_session = await dbs.scalar(
                select(WebAdminSession).where(WebAdminSession.token_hash == token_hash(raw_token))
            )
            if server_session:
                account = await dbs.get(WebStaffAccount, server_session.account_id)
            if (
                server_session
                and account
                and account.active
                and server_session.revoked_at is None
                and (server_session.expires_at is None or server_session.expires_at > now)
            ):
                valid = True
                if not server_session.last_seen_at or server_session.last_seen_at < now - timedelta(minutes=5):
                    server_session.last_seen_at = now
                    await dbs.commit()
            elif server_session and server_session.revoked_at is None:
                server_session.revoked_at = now
                await dbs.commit()

        if not valid or not account:
            session_cookie.clear()
            response = RedirectResponse("/admin/login", status_code=303)
            await response(scope, receive, send)
            return

        # Refresh identity from DB so role/disable changes take effect immediately.
        session_cookie["admin_auth"] = True
        session_cookie["admin_account_id"] = account.id
        session_cookie["admin_name"] = account.display_name
        session_cookie["admin_login"] = account.username
        session_cookie["admin_role"] = account.role
        session_cookie["admin_permissions"] = sorted(effective_permissions(account.role, account.permissions_json))

        current_permissions = set(session_cookie.get("admin_permissions") or [])
        request_method = str(scope.get("method") or "GET")
        required_permission = required_web_permission(path, request_method)
        if required_permission and required_permission not in current_permissions:
            response = HTMLResponse(
                f"<h1>403</h1><p>Недостатньо прав: <code>{required_permission}</code>.</p>",
                status_code=403,
            )
            await response(scope, receive, send)
            return
        any_permissions = required_web_any_permissions(path, request_method)
        if not required_permission and any_permissions and not current_permissions.intersection(any_permissions):
            response = HTMLResponse(
                "<h1>403</h1><p>Цей розділ не входить до ваших призначених прав доступу.</p>",
                status_code=403,
            )
            await response(scope, receive, send)
            return

        if account.must_change_password and path not in {"/admin/account/password", "/admin/logout"}:
            response = RedirectResponse("/admin/account/password?required=1", status_code=303)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Add browser hardening and staged CSP with a per-request nonce.

    v1.19.0 enforces an origin allow-list while keeping ``unsafe-inline`` for
    legacy inline event attributes that still exist in the Jinja UI. In
    parallel a nonce-first Report-Only policy exposes what remains to migrate
    before ``unsafe-inline`` can be removed safely.
    """

    def __init__(self, app, *, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(18)
        state = scope.setdefault("state", {})
        state["csp_nonce"] = nonce
        enforced_csp = (
            "default-src 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://telegram.org; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://api.telegram.org https://*.telegram.org; "
            "media-src 'self' blob:; worker-src 'self' blob:; manifest-src 'self'"
        )
        report_only_csp = (
            "default-src 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://telegram.org; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://api.telegram.org https://*.telegram.org; "
            "media-src 'self' blob:; worker-src 'self' blob:; manifest-src 'self'"
        )

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"same-origin"),
                    (b"permissions-policy", b"camera=(self), microphone=(), geolocation=()"),
                    (b"content-security-policy", enforced_csp.encode("ascii")),
                    (b"content-security-policy-report-only", report_only_csp.encode("ascii")),
                ])
                if str(scope.get("path") or "").startswith("/admin"):
                    headers.append((b"cache-control", b"no-store, private"))
                    headers.append((b"pragma", b"no-cache"))
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
