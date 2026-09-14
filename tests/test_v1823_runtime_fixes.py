from pathlib import Path

from app.ui_labels import IDEA_STATUSES, REQUEST_CATEGORIES, REQUEST_PRIORITIES, REQUEST_STATUSES

ROOT = Path(__file__).resolve().parents[1]


def test_ideas_and_requests_have_explicit_workflow_constants():
    assert "new" in IDEA_STATUSES and "implemented" in IDEA_STATUSES
    assert REQUEST_STATUSES == ("new", "in_review", "need_info", "resolved", "case_closed")
    assert "problem" in REQUEST_CATEGORIES and "technical" in REQUEST_CATEGORIES
    assert REQUEST_PRIORITIES == ("normal", "high", "critical")
    ideas = (ROOT / "app/web/routes/ideas.py").read_text(encoding="utf-8")
    requests = (ROOT / "app/web/routes/requests.py").read_text(encoding="utf-8")
    assert "from app.ui_labels import IDEA_STATUSES" in ideas
    assert "REQUEST_CATEGORIES, REQUEST_PRIORITIES, REQUEST_STATUSES" in requests


def test_calendar_uses_entries_not_dict_items_attribute():
    route = (ROOT / "app/web/routes/adminux.py").read_text(encoding="utf-8")
    template = (ROOT / "app/web/templates/calendar.html").read_text(encoding="utf-8")
    assert '"entries": by_day.get' in route
    assert "day.entries" in template
    assert "day.items" not in template


def test_telegram_qr_scanner_flow_is_wired():
    keyboard = (ROOT / "app/keyboards.py").read_text(encoding="utf-8")
    admin = (ROOT / "app/handlers/admin.py").read_text(encoding="utf-8")
    start = (ROOT / "app/handlers/start.py").read_text(encoding="utf-8")
    states = (ROOT / "app/states.py").read_text(encoding="utf-8")
    services = (ROOT / "app/services.py").read_text(encoding="utf-8")
    assert '("📷 QR-сканер", "admin:event_scanner")' in keyboard
    assert "AdminEventScannerState" in states
    assert 'F.data == "admin:event_scanner"' in admin
    assert 'F.data.startswith("admin:event_scanner_select:")' in admin
    assert 'F.data.startswith("admin:event_scanner_confirm:")' in admin
    assert 'payload.startswith("adminscan_")' in start
    assert 'payload.startswith("profile_")' in start
    assert "admin_scan_event_participant" in services


def test_web_scanner_has_cross_browser_telegram_path_and_no_duplicate_title_script():
    route = (ROOT / "app/web/routes/events.py").read_text(encoding="utf-8")
    template = (ROOT / "app/web/templates/event_detail.html").read_text(encoding="utf-8")
    assert '@router.get("/admin/events/{event_id}/scanner/telegram")' in route
    assert "adminscan_" in route
    assert "📲 Відкрити QR-сканер у Telegram" in template
    assert "🌐 Сканувати камерою браузера" in template
    assert template.startswith('{% extends "base.html" %}\n{% block title %}{{event.title}} • Подія{% endblock %}')
    assert template.count("const startBtn = document.getElementById('event-scanner-start');") == 1


def test_v1823_version():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "1.11.0"
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == "1.11.0"
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "/static/admin.css?v=1.11.0" in base
