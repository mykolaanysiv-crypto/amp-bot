"""Compatibility facade for event web routes after the v1.13.0 split.

Canonical event routes now live under ``app.web.event_routes``.  This file is
kept for 1–2 releases so ``app.web.routes.events.router`` remains stable.

Historical source-level markers:
@router.get("/admin/events/{event_id}/scanner/telegram")
"response_rate" / "invited"
adminscan_
"""
from app.web.event_routes import router

__all__ = ["router"]
