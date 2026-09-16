"""Compatibility facade for the AMP FastAPI application.

v1.13.0 moved composition into :func:`app.web.factory.create_app`.  The module-
level ``app`` remains for Uvicorn/Heroku and third-party imports during the
planned 1–2 release compatibility window.

Health routes now live in ``app.web.health_routes``:
/health/live
/health/ready
/health/dependencies
The datetime-safe JSON boundary uses ``jsonable_encoder`` there.
"""
from .factory import create_app

app = create_app()

__all__ = ["app", "create_app"]
