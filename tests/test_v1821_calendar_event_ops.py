from pathlib import Path

from app.models import Base, EventRegistration
from tests.source_layout import event_routes_source

ROOT = Path(__file__).resolve().parents[1]


def test_v1821_version_and_css_cache_buster():
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == version
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert f"/static/admin.css?v={(ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip()}" in base


def test_calendar_has_day_week_month_and_all_requested_sources():
    route = (ROOT / "app/web/routes/adminux.py").read_text(encoding="utf-8")
    template = (ROOT / "app/web/templates/calendar.html").read_text(encoding="utf-8")
    assert '{"day", "week", "month"}' in route
    for model in ["Event", "Quest", "VolunteerTask", "Survey", "Opportunity", "RequestCase", "Idea", "StreakFreeze"]:
        assert model in route
    for label in ["День", "Тиждень", "Місяць", "📅 Подія", "🎯 Квест", "✅ Задача", "📋 Опитування", "🌍 Можливість", "🆘 Кейс", "💡 Ідея", "❄️ Freeze"]:
        assert label in template
    assert "calendar-chip {{item.css}}" in template


def test_qr_scanner_is_on_event_page_and_camera_is_allowed_for_self():
    route = event_routes_source()
    template = (ROOT / "app/web/templates/event_detail.html").read_text(encoding="utf-8")
    middleware = (ROOT / "app/web/security_middleware.py").read_text(encoding="utf-8")
    assert '@router.post("/admin/events/{event_id}/scanner")' in route
    assert "BarcodeDetector" in template
    assert "getUserMedia" in template
    assert "📲 Відкрити QR-сканер у Telegram" in template
    assert "🌐 Сканувати камерою браузера" in template
    assert "Зареєструвати та підтвердити" in template
    assert "camera=(self)" in middleware


def test_waitlist_schema_and_two_hour_reservation_flow_exist():
    cols = {c.name for c in EventRegistration.__table__.columns}
    for name in {"waitlisted_at", "waitlist_promoted_at", "reservation_expires_at", "no_show_at"}:
        assert name in cols
    assert len(Base.metadata.tables) >= 53
    services = (ROOT / "app/domain_services/events.py").read_text(encoding="utf-8")
    handlers = (ROOT / "app/handlers/events.py").read_text(encoding="utf-8")
    keyboards = (ROOT / "app/keyboards.py").read_text(encoding="utf-8")
    assert "async def process_event_operations" in services
    assert 'events.waitlist_reservation_minutes' in services
    assert 'timedelta(minutes=reservation_minutes)' in services
    runtime_config = (ROOT / 'app/runtime_config.py').read_text(encoding='utf-8')
    assert 'RuleSpec("events.waitlist_reservation_minutes", "events", "Резерв черги очікування", 120' in runtime_config
    assert 'status = "reserved"' in services
    assert 'status = "waitlisted"' in services
    assert 'event_waitlist:' in handlers
    assert 'event_reserve_accept:' in handlers
    assert "⏳ Стати в чергу" in keyboards
    assert "✅ Підтвердити місце" in keyboards


def test_attendance_workflow_has_clear_statuses():
    labels = (ROOT / "app/ui_labels.py").read_text(encoding="utf-8")
    template = (ROOT / "app/web/templates/event_detail.html").read_text(encoding="utf-8")
    route = event_routes_source()
    for status, ua in [
        ("registered", "Зареєстрований"),
        ("cancelled", "Скасував"),
        ("waitlisted", "У черзі"),
        ("attended", "Був присутній"),
        ("no_show", "Не прийшов"),
    ]:
        assert f'"{status}": "{ua}"' in labels
    assert "event_registration_status_label(reg.status)" in template
    assert 'registrations/{registration_id}/no-show' in route
    assert 'reg.status = "no_show"' in route
