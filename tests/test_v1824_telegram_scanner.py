from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

from app.telegram_webapp import validate_webapp_init_data

ROOT = Path(__file__).resolve().parents[1]


def _signed_init_data(token: str, user_id: int = 12345) -> str:
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps({"id": user_id, "first_name": "Admin"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_telegram_webapp_init_data_signature():
    token = "123456:TESTTOKEN"
    raw = _signed_init_data(token, 777)
    user = validate_webapp_init_data(raw, token)
    assert user and user["id"] == 777
    assert validate_webapp_init_data(raw + "x", token) is None


def test_scanner_is_telegram_miniapp_and_continuous():
    admin = (ROOT / "app/handlers/admin.py").read_text(encoding="utf-8")
    routes = (ROOT / "app/web/routes/events.py").read_text(encoding="utf-8")
    template = (ROOT / "app/web/templates/telegram_event_scanner.html").read_text(encoding="utf-8")
    assert "WebAppInfo" in admin
    assert 'web_app=WebAppInfo(url=f"{base}/tg/event-scanner/{event.id}")' in admin
    assert '@router.get("/tg/event-scanner/{event_id}"' in routes
    assert '@router.post("/tg/event-scanner/{event_id}/scan")' in routes
    assert "showScanQrPopup" in template
    assert "return false" in template
    assert "window.addEventListener('load'" in template
    assert "miniapp_scan:" in routes
    assert "Бейдж відскановано" in routes


def test_version_broadcast_has_distributed_startup_lock():
    source = (ROOT / "app/web/app.py").read_text(encoding="utf-8")
    assert 'job_lock(db, f"version_announce:{APP_VERSION}"' in source
    assert "_announce_version_update_locked" in source


def test_v1824_version():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "1.11.1"
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == "1.11.1"
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "/static/admin.css?v=1.11.1" in base
