from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_version_and_schema_are_stable():
    assert read("VERSION.txt").strip() == "1.17.0.3"
    assert read("VERSION_CHECK.txt").strip() == "1.17.0.3"
    migration = read("migrations/versions/20260919_0007_giveaways.py")
    assert 'revision: str = "20260919_0007"' in migration


def test_event_detail_has_manual_feedback_resend_action():
    template = read("app/web/templates/event_detail.html")
    overview = read("app/web/event_routes/overview.py")
    assert 'id="event-feedback"' in template
    assert 'action="/admin/events/{{event.id}}/feedback/resend"' in template
    assert "🔁 Повторно надіслати відгук" in template
    assert "feedback_stats.pending" in template
    assert 'feedback_stats["pending"]' in overview


def test_manual_feedback_resend_targets_only_incomplete_attendees_and_uses_outbox():
    source = read("app/web/event_routes/mutations.py")
    assert '@router.post("/admin/events/{event_id}/feedback/resend")' in source
    assert 'guard_permission(request, "events.edit")' in source
    assert 'EventRegistration.status == "attended"' in source
    assert 'User.status == UserStatus.ACTIVE.value' in source
    assert 'feedback.status == "completed"' in source
    assert 'queue_telegram_delivery(' in source
    assert 'source="event_feedback_manual_resend"' in source
    assert 'entity_type=entity_type, entity_id=feedback.id' in source
    assert 'event_feedback:manual:' in source
    for entity_type in [
        "event_feedback_rating",
        "event_feedback_useful",
        "event_feedback_knowledge",
        "event_feedback_safe",
        "event_feedback_return",
    ]:
        assert entity_type in source
