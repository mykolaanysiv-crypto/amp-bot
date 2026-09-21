from pathlib import Path

from app.model_domains import Base
from app.registration_ux import decrypt_draft, encrypt_draft, registration_progress
from tests.source_layout import event_routes_source, main_source, models_source, start_source

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1110_version_schema_and_assets():
    version = text("VERSION.txt").strip()
    assert version
    assert text("VERSION_CHECK.txt").strip() == version
    assert len(Base.metadata.tables) >= 53
    assert "registration_journeys" in Base.metadata.tables
    assert f"/static/admin.css?v={text('VERSION.txt').strip()}" in text("app/web/templates/base.html")


def test_registration_progress_and_encrypted_resume_draft():
    assert "Крок 1 із 10" in registration_progress("privacy_notice")
    assert "Крок 10 із 10" in registration_progress("media_consent")
    secret = "x" * 64
    payload = {"first_name": "Микола", "email": "person@example.com", "phone": "+380671234567"}
    encrypted = encrypt_draft(secret, payload)
    assert "Микола" not in encrypted
    assert "person@example.com" not in encrypted
    assert decrypt_draft(secret, encrypted) == payload


def test_registration_ux_has_resume_buttons_autocomplete_and_validation():
    src = start_source()
    for token in [
        "reg:resume", "reg:restart", "registration_progress", "_settlement_keyboard",
        "reg:settlement:", "_vulnerability_keyboard", "reg:vuln:",
        "Не вдалося розпізнати прізвище", "Це не схоже на email",
        "Дата народження не може бути в майбутньому",
    ]:
        assert token in src
    assert "draft_ciphertext" in models_source()


def test_registration_funnel_is_wired_through_approval_and_first_activity():
    ux = text("app/registration_ux.py")
    users = text("app/web/routes/users.py")
    services = text("app/domain_services/gamification.py")
    dashboard = text("app/web/routes/dashboard.py")
    for stage in ["start", "consent", "profile", "submit", "approved", "first_activity"]:
        assert f'"{stage}"' in ux
    assert "mark_registration_approved" in users
    assert "mark_first_activity" in services
    assert "registration_funnel_counts" in dashboard


def test_requested_telegram_main_menu_order_and_contextual_home():
    kb = text("app/keyboards.py")
    expected = [
        '[KeyboardButton(text="🏠 Головна"), KeyboardButton(text="👤 Мій профіль")]',
        '[KeyboardButton(text="🚀 Долучитися"), KeyboardButton(text="⚡ Заробити XP")]',
        '[KeyboardButton(text="🌍 Можливості"), KeyboardButton(text="🎫 QR-бейдж")]',
        '[KeyboardButton(text="🤝 Запросити друга"), KeyboardButton(text="💙 Підтримати")]',
        '[KeyboardButton(text="🆘 Звернення")]',
        '[KeyboardButton(text="☰ Ще")]',
    ]
    positions = [kb.index(row) for row in expected]
    assert positions == sorted(positions)
    assert 'rows.append([KeyboardButton(text="🛠 Адмін-панель")])' in kb
    home = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    assert "Швидкі дії" not in home
    assert "Наступний крок" in home
    assert "pending_feedback" in home and "today_event" in home and "near_goal" in home
    assert "Продовжити реєстрацію" in home


def test_feedback_20_is_micro_and_has_one_deduped_reminder():
    feedback = text("app/handlers/feedback.py")
    main = main_source()
    runtime = text("app/runtime_config.py")
    assert "_replace_question" in feedback
    assert "Додати коментар" in feedback
    assert 'feedback.status = "completed"' in feedback
    assert "events.feedback_reminder_hours" in runtime
    assert 'dedupe_key=f"event_feedback:reminder:{fb.id}"' in main
    assert 'initial_delivery.status != "sent"' in main
    for entity_type in ["event_feedback_rating", "event_feedback_useful", "event_feedback_knowledge", "event_feedback_safe", "event_feedback_return"]:
        assert entity_type in main


def test_feedback_conversion_is_visible_per_event_and_overall():
    route = event_routes_source()
    event_tpl = text("app/web/templates/event_detail.html")
    dash_route = text("app/web/routes/dashboard.py")
    dash_tpl = text("app/web/templates/dashboard.html")
    assert '"response_rate"' in route and '"invited"' in route
    assert "Конверсія відгуків" in event_tpl
    assert "feedback_invited" in dash_route and "feedback_completed" in dash_route
    assert "Конверсія відгуків" in dash_tpl


def test_operations_dashboard_has_requested_operational_signals():
    route = text("app/web/routes/dashboard.py")
    tpl = text("app/web/templates/dashboard.html")
    for token in [
        "pending_registrations", "failed_notifications", "sla_overdue", "sla_due_soon",
        "upcoming_checkins", "today_no_show", "data_quality_issues",
    ]:
        assert token in route
    for label in ["Сьогодні", "Операційний стан", "Воронка реєстрації", "Прострочено строк реагування", "Проблеми якості даних"]:
        assert label in tpl


def test_monobank_and_sensitive_data_hardening():
    donations = text("app/donations.py")
    config = text("app/config.py")
    middleware = text("app/web/security_middleware.py")
    tpl = text("app/web/templates/donations.html")
    assert "exc.read()" not in donations
    assert 'state.jar_account_id = None' in donations
    assert 'User-Agent": f"AMPasadors/{APP_VERSION}"' in donations
    assert 'monobank_token: str = field(default="", repr=False)' in config
    assert 'web_session_secret: str = field(repr=False)' in config
    assert 'cache-control", b"no-store, private"' in middleware
    assert "show_sensitive_donation_data" in tpl
    assert "Доступно суперадміністратору" in tpl


def test_registration_draft_sensitive_answers_are_not_plaintext_funnel_columns():
    model = models_source()
    block = model[model.index("class RegistrationJourney"):model.index("class BanRecord")]
    assert "draft_ciphertext" in block
    for field in ["phone", "email", "settlement", "birth_date", "gender", "vulnerability"]:
        assert f"{field}: Mapped" not in block
