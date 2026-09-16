from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from ..observability import RequestContextMiddleware
from .dependencies import db, settings
from .lifespan import lifespan
from .security_middleware import AdminSessionValidationMiddleware, CSRFMiddleware, SecurityHeadersMiddleware
from . import auth_routes, health_routes, media_routes
from .routes import (
    dashboard as dashboard_routes,
    gamification as gamification_routes,
    analytics as analytics_routes,
    reports as reports_routes,
    surveys as surveys_routes,
    opportunities as opportunities_routes,
    users as users_routes,
    events as events_routes,
    quests as quests_routes,
    activities as activities_routes,
    tasks as tasks_routes,
    ideas as ideas_routes,
    requests as requests_routes,
    broadcasts as broadcasts_routes,
    system as system_routes,
    adminux as adminux_routes,
    notifications as notifications_routes,
    donations as donations_routes,
)


def create_app() -> FastAPI:
    """Application factory for the AMP web/admin process.

    v1.13.0 makes app construction explicit and keeps shared dependencies,
    lifespan/background work and route modules outside the composition root.
    """
    app = FastAPI(title="АМПасадори — панель керування", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware, service="web")
    # SessionMiddleware is intentionally added after the inner security layers
    # so the signed session is available to validation/CSRF middleware.
    app.add_middleware(AdminSessionValidationMiddleware, db=db)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web_session_secret,
        same_site="strict",
        https_only=settings.cookie_secure,
        max_age=60 * 60 * 24 * 30,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    for router in (health_routes.router, media_routes.router, auth_routes.router):
        app.include_router(router)

    for module in (
        dashboard_routes,
        gamification_routes,
        analytics_routes,
        reports_routes,
        surveys_routes,
        opportunities_routes,
        users_routes,
        events_routes,
        quests_routes,
        activities_routes,
        tasks_routes,
        ideas_routes,
        requests_routes,
        broadcasts_routes,
        system_routes,
        adminux_routes,
        notifications_routes,
        donations_routes,
    ):
        app.include_router(module.router)
    return app
