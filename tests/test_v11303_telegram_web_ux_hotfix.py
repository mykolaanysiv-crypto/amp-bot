from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v11303_version_is_synchronized():
    assert read("VERSION.txt").strip() == "1.13.0.3"
    assert read("VERSION_CHECK.txt").strip() == "1.13.0.3"
    assert '"1.13.0.3"' in read("app/version.py")


def test_start_and_menu_active_user_lazy_import_points_to_handlers_participant():
    source = read("app/handlers/start_flow/common.py")
    assert "from .. import participant" in source
    assert "from . import participant" not in source
    assert "await participant.overview(message, db)" in source


def test_menu_and_smart_are_exposed_and_smart_opens_personalized_opportunities():
    bot_runtime = read("app/bot_runtime.py")
    middleware = read("app/telegram_middleware.py")
    opportunities = read("app/handlers/participant_opportunities.py")
    help_source = read("app/handlers/start_flow/entry.py")

    assert 'BotCommand(command="menu", description="Головне меню")' in bot_runtime
    assert 'BotCommand(command="smart", description="Персональні можливості")' in bot_runtime
    assert 'Command("smart")' in opportunities
    assert "await refresh_matches_for_user(session, user)" in opportunities
    assert '"/smart"' in middleware
    assert "/smart — персональні можливості" in help_source


def test_reward_buttons_keep_complete_titles():
    source = read("app/keyboards.py")
    rewards_block = source[source.index("def rewards_keyboard"):source.index("def tasks_keyboard")]
    assert 'entity_button_text(f"🎁 {reward.title} · {reward.min_xp} XP")' in rewards_block
    assert "compact_button_text" not in rewards_block


def test_web_panel_visible_labels_are_ukrainian_for_known_regressions():
    templates = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app" / "web" / "templates").glob("*.html")
    )
    forbidden = (
        "Participant 360",
        "Referrals",
        ">Timeline<",
        "SEASONS & HISTORY",
        "❄️ Freeze",
        "SLA прострочено",
        "granular permission",
        "ручного override",
        ">Streak<",
    )
    for token in forbidden:
        assert token not in templates

    user_detail = read("app/web/templates/user_detail.html")
    assert "Профіль учасника 360°" in user_detail
    assert "Запрошення друзів" in user_detail
    assert "Хронологія" in user_detail

    calendar_route = read("app/web/routes/adminux.py")
    assert '"Заморозка серії"' in calendar_route
    event_ops = read("app/web/event_routes/operations.py")
    assert "check-in window" not in event_ops
    assert "ручного override" not in event_ops
    assert "Поза часовим вікном відмітки" in event_ops


def test_notification_center_localizes_internal_codes_instead_of_printing_them_raw():
    template = read("app/web/templates/notifications.html")
    route = read("app/web/routes/notifications.py")
    labels = read("app/ui_labels.py")
    assert "{{ label(row.type) }}" in template
    assert "{{ label(row.entity_type) if row.entity_type else '—' }}" in template
    assert "{{ label(row.status) }}" in template
    assert '("streak", "Серії участі")' in route
    for token in ('"queued": "У черзі"', '"retry": "Повторна спроба"', '"sent": "Надіслано"', '"failed": "Помилка"'):
        assert token in labels
