"""Canonical source-layout helpers for regression tests.

v1.13 split several historical monolith modules into domain packages while
keeping small compatibility facades.  Older regression tests intentionally
inspect source code for safety/UX invariants; they should inspect the canonical
implementation, not require those implementation strings to remain in facades.

Keep all source-location knowledge here so the next architecture move requires
one test-layout update instead of dozens of brittle path edits.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def concat(*rels: str) -> str:
    return "\n\n".join(text(rel) for rel in rels)


def _package_sources(rel_dir: str) -> tuple[str, ...]:
    root = ROOT / rel_dir
    return tuple(
        path.relative_to(ROOT).as_posix()
        for path in sorted(root.glob("*.py"))
        if path.name != "__pycache__"
    )


def main_source() -> str:
    """Telegram composition + runtime + all canonical scheduler jobs."""
    return concat(
        "app/main.py",
        "app/bot_runtime.py",
        "app/telegram_middleware.py",
        *_package_sources("app/jobs"),
    )


def start_source() -> str:
    """Registration/start compatibility facade plus canonical start flow."""
    return concat("app/handlers/start.py", *_package_sources("app/handlers/start_flow"))


def web_app_source() -> str:
    """FastAPI composition/runtime source after the application-factory split."""
    return concat(
        "app/web/app.py",
        "app/web/factory.py",
        "app/web/dependencies.py",
        "app/web/auth_routes.py",
        "app/web/health_routes.py",
        "app/web/media_routes.py",
        "app/web/lifespan.py",
        "app/web/broadcast_runtime.py",
    )


def event_routes_source() -> str:
    """Event compatibility facade plus all canonical event route modules."""
    return concat("app/web/routes/events.py", *_package_sources("app/web/event_routes"))


def models_source() -> str:
    """Model compatibility facade plus all canonical domain model modules."""
    # identity.py must remain contiguous so legacy structural assertions that
    # inspect RegistrationJourney -> BanRecord continue to validate the model.
    ordered = (
        "app/model_domains/base.py",
        "app/model_domains/identity.py",
        "app/model_domains/gamification.py",
        "app/model_domains/events.py",
        "app/model_domains/engagement.py",
        "app/model_domains/donations.py",
        "app/model_domains/communications.py",
        "app/model_domains/__init__.py",
    )
    return concat("app/models.py", *ordered)


def analytics_source() -> str:
    """Analytics facade plus canonical analytics implementation/export modules."""
    return concat("app/analytics.py", *_package_sources("app/analytics_modules"))


def reports_source() -> str:
    """Reporting facade plus canonical period/builder/export modules."""
    return concat("app/reports.py", *_package_sources("app/reporting"))


def broadcast_runtime_source() -> str:
    return text("app/web/broadcast_runtime.py")


def event_operations_source() -> str:
    return text("app/web/event_routes/operations.py")


def telegram_scanner_source() -> str:
    return text("app/web/event_routes/telegram_scanner.py")
