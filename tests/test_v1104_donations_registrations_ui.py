from pathlib import Path

from tests.source_layout import analytics_source, models_source, reports_source

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1104_version_and_css_cache():
    version = text("VERSION.txt").strip()
    assert version
    assert text("VERSION_CHECK.txt").strip() == version
    assert f"/static/admin.css?v={text('VERSION.txt').strip()}" in text("app/web/templates/base.html")


def test_donation_models_permissions_and_sidebar_exist():
    models = models_source()
    for name in ("DonationJarState", "DonationTransaction", "DonationReport", "SupportPageView"):
        assert f"class {name}" in models
    assert '"donations.manage"' in text("app/permissions.py")
    base = text("app/web/templates/base.html")
    assert "💙 Донати" in base
    assert 'href="/admin/donations"' in base


def test_telegram_support_and_reporting_flow():
    handler = text("app/handlers/donations.py")
    kb = text("app/keyboards.py")
    assert "💙 Підтримати" in handler and "💙 Підтримати" in kb
    assert "📄 Звітність" in handler
    assert "settings.donation_jar_url" in handler
    assert "SupportPageView" in handler
    assert "АМП-" in handler


def test_monobank_sync_and_badges_match_requested_thresholds():
    src = text("app/donations.py")
    assert 'MONOBANK_API = "https://api.monobank.ua"' in src
    assert '"Мій перший донат"' in src and '"criteria_value": 5000' in src
    assert '"Мажор"' in src and '"criteria_value": 20000' in src
    assert '"Мафіозі"' in src and '"criteria_value": 50000' in src
    assert '"Меценат"' in src and '"criteria_value": 100000' in src
    assert '"Почесний спонсор АМП"' in src and '"criteria_value": 200000' in src
    assert '"Брюс Всемогутній"' in src and '"criteria_value": 500000' in src
    assert 'badge_type": "ambassador"' in src
    assert 'total > threshold' in src
    assert '"/personal/client-info"' in src
    assert 'f"/personal/statement/{jar_id}/' in src


def test_donations_web_has_monitoring_reporting_and_analytics():
    route = text("app/web/routes/donations.py")
    tpl = text("app/web/templates/donations.html")
    for token in ("total_collected", "largest_donation", "average_donation", "donor_count", "support_views", "unique_support_users", "spent_total", "daily_rows", "jar_progress"):
        assert token in route
    for label in ("Зібрано", "Найбільший донат", "Середній донат", "Донатери", "Сторінка підтримки", "Звітність", "Транзакції"):
        assert label in tpl
    assert 'name="document"' in tpl
    assert 'name="amount_spent"' in tpl


def test_registrations_are_separate_intake_queue():
    route = text("app/web/routes/users.py")
    tpl = text("app/web/templates/registrations.html")
    base = text("app/web/templates/base.html")
    assert '@router.get("/admin/registrations"' in route
    assert 'User.registration_review_status == "approved"' in route
    assert 'User.registration_review_status == "pending"' in route
    assert 'web_user_registration_approved' in route
    assert 'web_user_registration_rejected' in route
    assert 'href="/admin/registrations"' in base
    for label in ("Очікують", "Схвалено сьогодні", "Відхилено", "Дата", "ПІБ", "Вік", "Населений пункт", "Telegram", "Телефон", "Статус", "Дії", "👁 Переглянути", "✅ Схвалити", "❌ Відхилити"):
        assert label in tpl


def test_opportunities_support_photos_in_web_and_telegram():
    model = models_source()
    route = text("app/web/routes/opportunities.py")
    tpl = text("app/web/templates/opportunities.html")
    tg = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    assert "class Opportunity" in model and "image_path" in model
    assert 'photo: UploadFile | None = File(None)' in route
    assert 'enctype="multipart/form-data"' in tpl
    assert "Фото можливості" in tpl
    assert "telegram_photo_input(db, item.image_path)" in tg


def test_superadmin_can_see_unsuppressed_aggregate_analytics():
    analytics = analytics_source()
    route = text("app/web/routes/analytics.py")
    tpl = text("app/web/templates/analytics.html")
    assert "reveal_sensitive_counts" in analytics
    assert "not reveal_sensitive_counts" in analytics
    assert "reveal_sensitive_counts=is_superadmin(request)" in route
    assert "Повна агрегована статистика" in tpl


def test_theme_mobile_overflow_dark_danger_and_permission_ui_fixes():
    base = text("app/web/templates/base.html")
    css = text("app/web/static/admin.css")
    security = text("app/web/templates/security_accounts.html")
    # No theme switcher remains in the sidebar; responsive top bars show one at a time.
    sidebar = base[base.index('<aside class="sidebar"'):base.index('</aside>')]
    assert "toggleTheme" not in sidebar
    assert base.count('onclick="toggleTheme()"') == 1
    assert "body[data-theme=\"dark\"] .entity-action-form.destructive-form" in css
    assert ".unified-action-button{min-width:0!important;width:100%!important;max-width:100%!important}" in css
    assert ".upcoming-item{min-width:0;max-width:100%;width:100%;box-sizing:border-box;overflow:hidden}" in css
    assert ".permission-actions{display:grid!important" in css
    assert '<details class="permission-editor">' in security
    assert '<details class="permission-editor" open' not in security


def test_selected_visible_english_labels_are_translated():
    visible = "\n".join(text(path) for path in (
        "app/web/templates/security_accounts.html",
        "app/web/templates/system_health.html",
        "app/web/templates/event_detail.html",
        "app/web/templates/opportunities.html",
    ))
    for forbidden in ("granular permissions", "QR Scanner", "Feedback після події", "Advanced Analytics", "SMART OPPORTUNITIES", "Manual override"):
        assert forbidden not in visible


def test_dashboard_data_quality_text_is_ukrainian():
    dashboard = text("app/web/templates/dashboard.html")
    assert "Канонічний довідник" in dashboard
    assert "Canonical-довідник" not in dashboard


def test_superadmin_reports_can_use_exact_aggregate_counts():
    reports = reports_source()
    route = text("app/web/routes/reports.py")
    assert "reveal_sensitive_counts: bool = False" in reports
    assert "not reveal_sensitive_counts" in reports
    assert "reveal_sensitive_counts=is_superadmin(request)" in route
    assert "ПІБ, контакти й списки конкретних осіб не формуються" in reports


def test_opportunity_photo_column_has_existing_database_migration():
    db = text("app/db.py")
    # The migrations mapping must have a single opportunities key; duplicate keys
    # would silently drop image_path for databases upgraded from v1.10.3.
    migration_block = db[db.index("migrations: dict"):db.index("for table, specs in migrations.items()") if "for table, specs in migrations.items()" in db else len(db)]
    assert migration_block.count('"opportunities": [') == 1
    opp = migration_block[migration_block.index('"opportunities": ['):migration_block.index('"ideas": [') ]
    assert '("image_path", "VARCHAR(500)")' in opp


def test_donation_badges_have_ukrainian_labels_and_protected_rules():
    labels = text("app/ui_labels.py")
    tpl = text("app/web/templates/badges.html")
    route = text("app/web/routes/gamification.py")
    for code, title in (("donation_first", "Перший донат від суми"), ("donation_single", "Разовий донат від суми"), ("donation_total_over", "Сумарні донати понад суму")):
        assert f'"{code}": "{title}"' in labels
    assert "Системний донатний бейдж" in tpl
    assert "b.criteria_value / 100" in tpl
    assert 'donation_criteria = {"donation_first", "donation_single", "donation_total_over"}' in route


def test_support_copy_uses_amp_code_not_english_id_label():
    handler = text("app/handlers/donations.py")
    participant = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    assert "свій АМП-код" in handler
    assert "ID АМП" not in participant
    assert "АМП-код:" in participant


def test_login_assets_use_current_release_cache_version():
    for path in ("app/web/templates/login.html", "app/web/templates/login_2fa.html", "app/web/templates/base.html"):
        src = text(path)
        assert "?v=1.7.3" not in src
        assert "?v=1.8.0" not in src
        assert f"?v={text('VERSION.txt').strip()}" in src
