from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse


def test_v11216_or_newer_and_version_files_match():
    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    check = Path("VERSION_CHECK.txt").read_text(encoding="utf-8").strip()
    assert version == check
    assert tuple(int(part) for part in version.split(".")) >= (1, 12, 1, 6)


def test_health_response_encodes_native_datetime_before_jsonresponse():
    source = Path("app/web/app.py").read_text(encoding="utf-8")
    assert "from fastapi.encoders import jsonable_encoder" in source
    assert "JSONResponse(jsonable_encoder(payload)" in source

    # Reproduce the production failure mode without importing the full web app.
    payload = {
        "status": "ok",
        "worker": {
            "at": datetime(2026, 9, 15, 11, 35, 31),
            "started_at": datetime(2026, 9, 15, 11, 30, 18, tzinfo=timezone.utc),
        },
    }
    response = JSONResponse(jsonable_encoder(payload))
    body = response.body.decode("utf-8")
    assert '"at":"2026-09-15T11:35:31"' in body
    assert '"started_at":"2026-09-15T11:30:18+00:00"' in body


def test_health_dependency_endpoint_still_returns_degraded_instead_of_crashing():
    source = Path("app/web/app.py").read_text(encoding="utf-8")
    assert '@app.get("/health/dependencies")' in source
    assert '"status": "ok" if overall else "degraded"' in source
    assert "200 if overall else 503" in source
