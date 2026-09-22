from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v11724_version_and_alembic_chain():
    version = text("VERSION.txt").strip()
    assert tuple(int(x) for x in version.split(".")) >= (1, 17, 2, 4)
    assert text("VERSION_CHECK.txt").strip() == version
    migration = text("migrations/versions/20260921_0013_event_end_and_quest_proofs.py")
    assert 'revision: str = "20260921_0013"' in migration
    assert 'down_revision: Union[str, None] = "20260921_0012"' in migration
    assert '"ends_at"' in migration
    assert '"proof_photo_path"' in migration


def test_event_and_quest_models_have_new_fields():
    events = text("app/model_domains/events.py")
    engagement = text("app/model_domains/engagement.py")
    assert "ends_at:" in events and "mapped_column(DateTime" in events
    assert "proof_photo_path:" in engagement


def test_quest_submission_asks_for_optional_photo_and_stores_private_proof():
    states = text("app/states.py")
    handler = text("app/handlers/quests.py")
    security = text("app/security.py")
    assert "class QuestProofState" in states
    assert 'callback_data=f"quest_proof_yes:{quest_id}"' in handler
    assert 'callback_data=f"quest_proof_no:{quest_id}"' in handler
    assert "QuestProofState.photo" in handler
    assert 'save_telegram_photo(bot, message.photo[-1].file_id, "quest_proofs"' in handler
    assert "Ваш запит на виконання квесту передано на обробку" in handler
    assert '"quest_proofs"' in security


def test_superadmin_can_force_approve_joined_quest_with_reason():
    route = text("app/web/routes/quests.py")
    template = text("app/web/templates/quest_detail.html")
    assert 'action == "force-approve"' in route
    assert "guard_superadmin(request)" in route
    assert 'part.status in {"joined", "returned", "completed"}' in route
    assert "мінімум 5 символів" in route
    assert "web_quest_force_approve" in route
    assert "Виконано вручну" in template


def test_event_checkin_window_is_around_start_and_explicit_end():
    config = text("app/runtime_config.py")
    service = text("app/domain_services/events.py")
    schedule = text("app/event_schedule.py")
    assert 'RuleSpec("events.checkin_open_before_minutes", "events", "Відкрити відмітку до події", 60' in config
    assert 'RuleSpec("events.checkin_close_after_end_minutes", "events", "Закрити відмітку після завершення", 60' in config
    assert 'get_runtime_int(session, "events.checkin_open_before_minutes")' in service
    assert 'get_runtime_int(session, "events.checkin_close_after_end_minutes")' in service
    assert "event_finish_utc = event_end_utc(event)" in service
    assert "closes_at_utc = event_finish_utc + timedelta(minutes=after)" in service
    assert "event.ends_at" in schedule or "getattr(event, \"ends_at\"" in schedule


def test_feedback_is_sent_after_event_end_and_to_actual_participants():
    config = text("app/runtime_config.py")
    job = text("app/jobs/events.py")
    assert 'RuleSpec("events.feedback_after_end_minutes", "events", "Зворотний зв’язок після завершення", 10' in config
    assert 'get_runtime_int(session, "events.feedback_after_end_minutes")' in job
    assert 'EventRegistration.status.in_(["checked_in", "attended"])' in job
    assert "anchor_utc = event_end_utc(event)" in job
    assert "anchor_utc + timedelta(minutes=feedback_delay_minutes)" in job
    assert "await asyncio.sleep(60)" in job


def test_event_forms_collect_start_and_end_and_web_has_live_regions():
    events_tpl = text("app/web/templates/events.html")
    detail_tpl = text("app/web/templates/event_detail.html")
    base = text("app/web/templates/base.html")
    mutations = text("app/web/event_routes/mutations.py")
    for name in ["end_day", "end_month", "end_year", "end_time"]:
        assert f'name="{name}"' in events_tpl
    assert "ends_at <= starts_at" in mutations
    assert 'data-live-region="event-cards-live"' in events_tpl
    assert "data-live-region" in detail_tpl
    assert "window.setInterval(sync,POLL_MS)" in base
    assert "POLL_MS=15000" in base.replace(" ", "")
    assert "fetch(location.href" in base


def test_web_edits_push_current_event_and_quest_data_to_telegram():
    event_mutations = text("app/web/event_routes/mutations.py")
    quest_routes = text("app/web/routes/quests.py")
    assert "🔄 <b>Оновлено подію</b>" in event_mutations
    assert "дані вже актуальні" in event_mutations
    assert "🔄 <b>Оновлено квест" in quest_routes
