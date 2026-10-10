from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v1203_version_and_assets_are_wired():
    assert read("VERSION.txt").strip() == "1.20.3.1"
    assert read("VERSION_CHECK.txt").strip() == "1.20.3.1"
    base = read("app/web/templates/base.html")
    assert '/static/admin.css?v=1.20.3.1' in base
    assert '/static/refinement.js?v=1.20.3.1' in base
    build = read("scripts/build_admin_css.py")
    assert '"refinement.css"' in build
    assert (ROOT / "app/web/static/reward-placeholder.svg").exists()


def test_refinement_fixes_nested_icon_and_wrapping_regressions():
    css = read("app/web/static/refinement.css")
    assert ".report-feature-grid>span" in css
    assert ".report-feature-grid>span>.icon" in css
    assert "word-break:normal!important" in css
    assert "white-space:nowrap!important" in css
    assert "--content-wide:1720px" in css
    assert ".amp-modal.amp-editor-modal" in css


def test_help_quick_start_switches_categories_without_polluting_search():
    tpl = read("app/web/templates/help.html")
    js = read("app/web/static/refinement.js")
    for category in ("events", "people", "gamification", "security"):
        assert f'data-help-category-target="{category}"' in tpl
    assert 'data-help-query="події QR реєстрація"' not in tpl
    assert "activateCategory" in js
    assert "data-help-category-target" in js


def test_semantic_icon_system_covers_priority_modules():
    macro = read("app/web/templates/_ui_macros.html")
    for name in (
        "registration", "user-check", "team", "event", "calendar-start",
        "calendar-end", "quest", "volunteer", "journey", "catalog",
        "reward", "history", "settings-section",
    ):
        assert f"name == '{name}'" in macro


def test_priority_pages_use_semantic_icons_and_full_width_components():
    assert "icon('registration')" in read("app/web/templates/registrations.html")
    assert "icon('team')" in read("app/web/templates/ambassadors.html")
    assert "icon('event')" in read("app/web/templates/events.html")
    assert "icon('quest')" in read("app/web/templates/quests.html")
    assert "icon('volunteer')" in read("app/web/templates/tasks.html")
    assert "icon('journey')" in read("app/web/templates/activities.html")
    assert "icon('report')" in read("app/web/templates/reports.html")
    assert "reward-placeholder.svg?v=1.20.3.1" in read("app/web/templates/rewards.html")


def test_opportunity_share_actions_are_not_duplicated():
    tpl = read("app/web/templates/opportunity_detail.html")
    assert "data-share-url" in tpl
    assert "Відкрити" in tpl
    assert "data-copy-url" not in tpl


def test_refinement_motion_respects_reduced_motion():
    css = read("app/web/static/refinement.css")
    js = read("app/web/static/refinement.js")
    assert "prefers-reduced-motion:reduce" in css
    assert "prefers-reduced-motion: reduce" in js
    assert "IntersectionObserver" in js
