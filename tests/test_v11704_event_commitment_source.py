from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_event_commitment_schema_and_migration_present():
    model = read("app/model_domains/events.py")
    migration = read("migrations/versions/20260920_0008_event_commitment_xp.py")
    assert "preregistration_bonus_xp" in model
    assert "no_show_penalty_xp" in model
    assert "attendance_xp_awarded" in model
    assert "no_show_penalty_xp_applied" in model
    assert 'revision: str = "20260920_0008"' in migration
    assert 'down_revision: Union[str, None] = "20260919_0007"' in migration


def test_event_reward_reconciliation_and_superadmin_override_present():
    source = read("app/domain_services/events.py")
    assert "event_preregistration_bonus_eligible" in source
    assert "reconcile_event_registration_rewards" in source
    assert "target_status == \"attended\"" in source
    assert "target_status == \"no_show\"" in source
    assert "force_event_registration_status" in source
    assert "registration_source == \"scanner\"" not in source  # getattr-based secure compatibility path
    assert 'getattr(reg, "registration_source", "legacy") == "scanner"' in source


def test_participant_cancellation_deadline_and_messages_present():
    events = read("app/handlers/events.py")
    reminders = read("app/jobs/events.py")
    assert "Після початку події скасування недоступне" in events
    assert "Штраф за неявку не застосовуватиметься" in events
    assert "За попередню реєстрацію + участь" in events
    assert "Неявка без скасування" in reminders


def test_web_superadmin_can_force_all_registration_statuses():
    operations = read("app/web/event_routes/operations.py")
    template = read("app/web/templates/event_detail.html")
    assert "superadmin_force_event_registration_status" in operations
    assert "guard_superadmin(request)" in operations
    for status in ("registered", "waitlisted", "reserved", "checked_in", "attended", "no_show", "cancelled"):
        assert f'value="{status}"' in template
    assert "Суперадмін: доступно незалежно від дати й часу" in template


def test_event_create_forms_expose_configurable_bonus_and_penalty():
    template = read("app/web/templates/events.html")
    states = read("app/states.py")
    admin_events = read("app/handlers/admin_events.py")
    assert 'name="preregistration_bonus_xp"' in template
    assert 'name="no_show_penalty_xp"' in template
    assert "preregistration_bonus_xp = State()" in states
    assert "no_show_penalty_xp = State()" in states
    assert "Рекомендовано 5 XP" in admin_events
