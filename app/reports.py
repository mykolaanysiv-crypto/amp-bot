"""Compatibility facade for Reporting 2.0 after the v1.13.0 split.

Canonical implementation now lives under ``app.reporting``.  This facade is
kept for the planned 1–2 release compatibility window.

Compatibility markers for historical source-level regression checks:
- "deleted_permanent_profiles"
- "avg_xp_per_engaged"
- "restored_profiles"
- get_runtime_int(session, "privacy.suppression_threshold")
- f"<{privacy_threshold}"
"""
from .reporting import (
    MONTHS_UA, resolve_report_period, resolve_report_storage_bounds,
    build_period_report, report_excel, report_pdf,
)

__all__ = [
    "MONTHS_UA", "resolve_report_period", "resolve_report_storage_bounds",
    "build_period_report", "report_excel", "report_pdf",
]
