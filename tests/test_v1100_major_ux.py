from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1100_version_and_cache():
    version = text("VERSION.txt").strip()
    assert version
    assert text("VERSION_CHECK.txt").strip() == version
    assert f"/static/admin.css?v={text('VERSION.txt').strip()}" in text("app/web/templates/base.html")


def test_compact_telegram_main_menu_and_hubs():
    kb = text("app/keyboards.py")
    for caption in ["🏠 Головна", "🚀 Долучитися", "🌍 Можливості", "👤 Мій профіль", "🎫 QR-бейдж", "☰ Ще"]:
        assert caption in kb
    for callback in [
        "ux:join:events", "ux:join:quests", "ux:join:volunteer", "ux:join:activities", "ux:join:ideas", "ux:join:surveys",
        "ux:mine:profile", "ux:mine:xp", "ux:mine:league", "ux:mine:streaks", "ux:mine:goals", "ux:mine:badges", "ux:mine:rewards",
        "ux:more:rules", "ux:more:help",
    ]:
        assert callback in kb
    main = text("app/main.py")
    assert 'F.data.startswith("ux:")' in main
    assert '"ux:mine:seasons"' in main


def test_my_amp_today_dashboard_exists():
    participant = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    assert 'F.text.in_({"🏠 Головна", "🏠 Огляд"})' in participant
    for token in ["Привіт", "До наступного рівня", "Найближче", "Квест", "персональних можливостей"]:
        assert token in participant
    start = text("app/handlers/start.py")
    assert "await participant.overview(message, db)" in start


def test_participant_360_tabs_all_have_icons():
    tpl = text("app/web/templates/user_detail.html")
    expected = [
        "🏠 Огляд", "🎯 Квести", "⚡ Активності", "⚡ XP", "📅 Події", "✅ Волонтерство",
        "💡 Ідеї", "📋 Опитування", "🏅 Бейджі", "🏆 Сезони", "📄 Документи",
    ]
    for label in expected:
        assert f">{label}</button>" in tpl


def test_runtime_settings_are_editable_and_used():
    cfg = text("app/runtime_config.py")
    for key in [
        "xp.birthday", "xp.idea_approved", "xp.referral_max", "xp.streak_restore_cost",
        "streak.freeze_limit_quarter", "streak.super_total_misses", "streak.badge_days",
        "events.reminder_minutes", "events.feedback_delay_minutes", "events.waitlist_reservation_minutes",
        "privacy.suppression_threshold", "privacy.retention_days",
    ]:
        assert key in cfg
    settings_tpl = text("app/web/templates/settings.html")
    settings_route = text("app/web/routes/adminux.py")
    assert 'action="/admin/settings"' in settings_tpl
    assert '@router.post("/admin/settings")' in settings_route
    assert "guard_permission" in settings_route
    assert "settings.manage" in settings_route
    usages = "\n".join(text(p) for p in [
        "app/services.py", "app/domain_services/gamification.py", "app/domain_services/referrals.py", "app/domain_services/events.py", "app/workflows.py", "app/leagues.py", "app/main.py",
        "app/analytics.py", "app/reports.py", "app/web/routes/gamification.py",
    ])
    for key in [
        "xp.birthday", "xp.idea_approved", "xp.referral_max", "xp.streak_restore_cost",
        "streak.freeze_limit_quarter", "streak.super_total_misses", "streak.badge_days",
        "events.reminder_minutes", "events.feedback_delay_minutes", "events.waitlist_reservation_minutes",
        "privacy.suppression_threshold",
    ]:
        assert key in usages


def test_privacy_threshold_is_not_hardcoded_in_analytics_exports():
    analytics = text("app/analytics.py")
    reports = text("app/reports.py")
    assert 'get_runtime_int(session, "privacy.suppression_threshold")' in analytics
    assert 'get_runtime_int(session, "privacy.suppression_threshold")' in reports
    assert 'f"<{privacy_threshold}"' in analytics
    assert 'f"<{privacy_threshold}"' in reports
