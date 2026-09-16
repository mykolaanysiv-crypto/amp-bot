"""Compatibility facade for analytics after the v1.13.0 architecture split.

Canonical code lives in ``app.analytics_modules``.  This facade remains for the
next 1–2 releases so existing imports keep working.

Compatibility notes retained for historical source-level checks:
- metrics include "lifecycle", "participation_mix", "restoration".
- privacy threshold is resolved with get_runtime_int(session, "privacy.suppression_threshold").
- suppressed labels use f"<{privacy_threshold}".
"""
from .analytics_modules import (
    METRIC_ORDER, METRIC_META, IDEA_STATUS_LABELS, build_analytics,
    analytics_excel, analytics_pdf, analytics_bot_text, analytics_png,
)

__all__ = [
    "METRIC_ORDER", "METRIC_META", "IDEA_STATUS_LABELS", "build_analytics",
    "analytics_excel", "analytics_pdf", "analytics_bot_text", "analytics_png",
]
