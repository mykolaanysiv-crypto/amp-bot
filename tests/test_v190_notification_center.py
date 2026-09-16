from pathlib import Path

from app.models import Base, EventFeedback, Notification
from tests.source_layout import analytics_source, event_routes_source, main_source, reports_source

ROOT = Path(__file__).resolve().parents[1]


def test_v190_version_and_schema():
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == version
    assert len(Base.metadata.tables) >= 53
    ncols = {c.name for c in Notification.__table__.columns}
    assert {
        "recipient_user_id", "recipient_tg_id", "type", "title", "body",
        "entity_type", "entity_id", "scheduled_at", "sent_at", "status",
        "error", "retry_count", "dedupe_key",
    } <= ncols
    fcols = {c.name for c in EventFeedback.__table__.columns}
    assert {"event_id", "user_id", "rating", "useful", "new_knowledge", "felt_safe", "would_return", "comment", "status", "prompted_at", "completed_at"} <= fcols


def test_notification_center_web_and_retry():
    route = (ROOT / "app/web/routes/notifications.py").read_text(encoding="utf-8")
    tpl = (ROOT / "app/web/templates/notifications.html").read_text(encoding="utf-8")
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert '"/admin/notifications"' in route
    assert '"/admin/notifications/retry-failed"' in route
    assert 'Notification.status == "failed"' in route
    assert "🔁 Повторити невдалі" in tpl
    assert "В черзі" in tpl and "Надіслано" in tpl and "Помилки" in tpl
    for label in ["Системні", "Події", "Розсилки", "Кейси", "Серії участі", "Опитування"]:
        assert label in route
    assert "🔔 Сповіщення" in base
    assert f"/static/admin.css?v={(ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip()}" in base


def test_all_proactive_telegram_delivery_uses_canonical_center():
    reliability = (ROOT / "app/reliability.py").read_text(encoding="utf-8")
    assert "async def queue_notification" in reliability
    assert "async def queue_telegram_delivery" in reliability
    assert "return await queue_notification(" in reliability
    assert "select(Notification)" in reliability
    assert "notification.status == \"sent\"" in reliability
    # Direct Bot API send is allowed only in the canonical delivery implementation,
    # the immediate Web 2FA code path, and the runtime-health emergency channel.
    # runtime_health is intentionally out-of-band: it must still alert superadmins
    # when the worker / Notification Center itself is unavailable. Business notices queue.
    offenders = []
    for p in (ROOT / "app").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if "bot.send_message" not in text:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in {"app/reliability.py", "app/web/auth_routes.py", "app/runtime_health.py"}:
            continue
        offenders.append(rel)
    assert offenders == []


def test_runtime_health_direct_delivery_is_superadmin_only_emergency_channel():
    runtime = (ROOT / "app/runtime_health.py").read_text(encoding="utf-8")
    assert "async def _direct_superadmin_alert" in runtime
    assert "for tg_id in sorted(settings.superadmin_ids)" in runtime
    assert "await bot.send_message(tg_id, text_value)" in runtime
    assert "runtime_health_alert" in runtime
    assert "Notification Center itself has stopped" not in runtime  # no false claim in user-facing alert


def test_legacy_outbox_migrates_idempotently():
    db = (ROOT / "app/db.py").read_text(encoding="utf-8")
    assert "legacy_notification_delivery:" in db
    assert "LEFT JOIN users u ON u.tg_id = nd.recipient_tg_id" in db
    assert "INSERT INTO notifications" in db
    assert "NOT EXISTS" in db


def test_feedback_scheduler_and_telegram_flow():
    main = main_source()
    handler = (ROOT / "app/handlers/feedback.py").read_text(encoding="utf-8")
    reliability = (ROOT / "app/reliability.py").read_text(encoding="utf-8")
    assert "_event_feedback_scheduler" in main
    assert 'get_runtime_int(session, "events.feedback_delay_minutes")' in main
    assert "timedelta(minutes=feedback_delay_minutes)" in main
    assert "EventRegistration.status == \"attended\"" in main
    assert "feedback:rating:" in handler
    assert "feedback:yn:" in handler
    for field in ["useful", "new_knowledge", "felt_safe", "would_return"]:
        assert field in handler
    assert "EventFeedbackState.comment" in handler
    assert "range(1, 6)" in reliability


def test_feedback_analytics_and_donor_reporting():
    events = event_routes_source()
    event_tpl = (ROOT / "app/web/templates/event_detail.html").read_text(encoding="utf-8")
    analytics = analytics_source()
    reports = reports_source()
    assert "feedback_stats" in events
    assert "Зворотний зв’язок та вплив" in event_tpl
    assert "Середня оцінка" in event_tpl
    assert "event_outcomes" in analytics
    assert "feedback_new_knowledge_pct" in analytics
    assert 'fig.text(.07,.93,"Вплив"' in reports
    assert "високо оцінили активності" in reports
    assert "повідомили про отримання нових знань" in reports
    assert "почувалися безпечно" in reports
    assert 'create_sheet("Вплив")' in reports
