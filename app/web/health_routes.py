from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .dependencies import APP_VERSION, db, settings
from ..runtime_health import alembic_revision_status, database_probe, expected_alembic_head, runtime_health_snapshot

router = APIRouter()

def _health_response(payload: dict, status_code: int = 200) -> JSONResponse:
    # runtime health snapshots intentionally keep native datetime objects for
    # internal/admin consumers. Encode only at the HTTP boundary so health
    # endpoints can always return valid JSON instead of raising TypeError.
    return JSONResponse(jsonable_encoder(payload), status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/health/live")
async def health_live():
    """Process liveness only; never contacts external dependencies."""
    return _health_response({"status": "ok", "service": "web", "version": APP_VERSION})


@router.get("/health/ready")
async def health_ready(request: Request):
    """Web readiness: startup completed, PostgreSQL answers and Alembic is at head."""
    startup_complete = bool(getattr(request.app.state, "startup_complete", False))
    db_status = await database_probe(db, timeout_seconds=settings.health_probe_timeout_seconds)
    migration = {"ok": False, "current": None, "expected": expected_alembic_head()}
    if db_status["ok"]:
        migration = await alembic_revision_status(db, expected_head=migration["expected"] or "")
    ready = bool(startup_complete and db_status["ok"] and migration.get("ok"))
    return _health_response(
        {
            "status": "ready" if ready else "not_ready",
            "version": APP_VERSION,
            "startup_complete": startup_complete,
            "database": db_status,
            "alembic": migration,
        },
        200 if ready else 503,
    )


@router.get("/health/dependencies")
async def health_dependencies():
    """Full system dependency status for external monitoring and diagnostics."""
    db_status = await database_probe(db, timeout_seconds=settings.health_probe_timeout_seconds)
    expected_head = expected_alembic_head()
    migration = {"ok": False, "current": None, "expected": expected_head}
    runtime = {"ok": False, "worker_ok": False, "schedulers_ok": False, "worker": {}, "schedulers": []}
    if db_status["ok"]:
        migration = await alembic_revision_status(db, expected_head=expected_head)
        try:
            async with db.session_factory() as session:
                runtime = await runtime_health_snapshot(
                    session,
                    worker_stale_seconds=settings.worker_stale_seconds,
                    startup_grace_seconds=settings.health_startup_grace_seconds,
                )
        except Exception as exc:
            runtime = {
                "ok": False, "worker_ok": False, "schedulers_ok": False,
                "worker": {}, "schedulers": [], "error": type(exc).__name__,
            }
    overall = bool(db_status["ok"] and migration.get("ok") and runtime.get("ok"))
    return _health_response(
        {
            "status": "ok" if overall else "degraded",
            "version": APP_VERSION,
            "database": db_status,
            "pool": db.pool_status(),
            "alembic": migration,
            "worker": runtime.get("worker", {}),
            "schedulers_ok": runtime.get("schedulers_ok", False),
            "schedulers": runtime.get("schedulers", []),
        },
        200 if overall else 503,
    )


@router.get("/health")
async def health():
    """Backward-compatible lightweight liveness endpoint."""
    return _health_response({"status": "ok", "version": APP_VERSION})
