from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_and_schema_stay_compatible():
    version = read("VERSION.txt").strip()
    assert version.startswith("1.")
    assert read("VERSION_CHECK.txt").strip() == version
    assert '20260915_0002' in read("migrations/versions/20260915_0002_content_views.py")


def test_profile_xp_uses_canonical_transaction_description():
    source = read("app/handlers/participant_home.py")
    assert "row.description or row.category" in source
    assert "row.reason or row.category" not in source
    assert '"ux:mine:xp": lambda: participant.xp_history' in read("app/bot_runtime.py")


def test_badges_have_catalog_mine_and_automatic_notifications():
    home = read("app/handlers/participant_home.py")
    gamification = read("app/domain_services/gamification.py")
    assert 'text="🏅 Усі бейджі"' in home
    assert 'text="✅ Мої бейджі"' in home
    assert 'callback_data="badges:all"' in home
    assert 'callback_data="badges:mine"' in home
    assert "які бейджі існують і за що їх можна отримати" in home
    assert "Вітаємо! Ви отримали новий бейдж" in gamification
    assert 'dedupe_key=f"automatic_badge:{user.id}:{badge.id}"' in gamification
    assert 'button_text="🏅 Переглянути бейджі"' in gamification


def test_super_streak_name_marker_supports_optional_animated_custom_emoji():
    source = read("app/handlers/participant_home.py")
    assert "TELEGRAM_FIRE_CUSTOM_EMOJI_ID" in source
    assert '<tg-emoji emoji-id=' in source
    assert "streak_fire = _super_streak_fire" in source
    assert "escape(user.full_name)" in source


def test_admin_search_alignment_matches_sidebar_breakpoints():
    css = read("app/web/static/admin.css")
    assert "@media (min-width:1920px){.admin-topbar{left:300px}}" in css
    assert "@media (min-width:1024px) and (max-width:1365px){.admin-topbar{left:232px}}" in css
    assert ".global-search-top{min-width:0" in css


def test_analytics_clickthrough_and_superadmin_drilldown_exist():
    dashboard = read("app/web/templates/analytics.html")
    detail = read("app/web/templates/analytics_detail.html")
    route = read("app/web/routes/analytics.py")
    assert "analytics-chart-clickable" in dashboard
    assert "data-detail-url" in dashboard
    assert "{% if is_superadmin %}" in detail
    assert "Деталізація вибраного значення" in detail
    assert "Вид даних" in detail
    assert "Група / категорія" in detail
    assert "analytics_data_scope" in route
