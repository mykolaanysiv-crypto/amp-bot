from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v12031_version_and_polish_assets_are_wired():
    assert read("VERSION.txt").strip() == "1.20.3.1"
    assert read("VERSION_CHECK.txt").strip() == "1.20.3.1"
    base = read("app/web/templates/base.html")
    assert '/static/admin.css?v=1.20.3.1' in base
    assert '/static/polish.js?v=1.20.3.1' in base
    assert 'desktop-sidebar-toggle' not in base
    build = read("scripts/build_admin_css.py")
    assert '"polish.css"' in build


def test_v12031_never_splits_control_words_and_reduces_shadows():
    css = read("app/web/static/polish.css")
    assert "hyphens:none" in css
    assert "word-break:keep-all" in css
    assert "white-space:nowrap" in css
    assert "--shadow-md:0 6px 18px" in css
    assert ".primary:hover" in css


def test_v12031_operations_severity_is_accent_not_card_fill():
    exp = read("app/web/static/experience.css")
    css = read("app/web/static/polish.css")
    assert ".severity-dot.severity-high" in exp
    assert "\n.severity-high{background:" not in exp
    assert ".ops-card.severity-high" in css
    assert "background:var(--color-surface)!important" in css


def test_v12031_toasts_are_compact_bottom_left_and_closeable():
    css = read("app/web/static/polish.css")
    js = read("app/web/static/polish.js")
    assert ".amp-toast-region" in css
    assert "bottom:20px" in css
    assert "left:calc(var(--sidebar-expanded) + 22px)" in css
    assert "amp-toast-close" in js
    assert "window.AMPToast" in js
    assert "data-toast-source" in js


def test_v12031_modals_are_centered_and_empty_editors_are_blocked():
    css = read("app/web/static/polish.css")
    js = read("app/web/static/polish.js")
    assert "inset:50% auto auto 50%" in css
    assert "transform:translate(-50%,-50%)" in css
    assert "amp-editor-modal" in js
    assert "немає даних для редагування" in js


def test_v12031_overview_uses_semantic_icons():
    macro = read("app/web/templates/_ui_macros.html")
    dashboard = read("app/web/templates/dashboard.html")
    base = read("app/web/templates/base.html")
    for name in ("dashboard", "tasks", "xp", "opportunity", "streak", "season", "gamification", "notification"):
        assert f"name == '{name}'" in macro
    for token in ("kpi-icon", "icon('event')", "icon('user-check')", "icon('xp')", "icon('tasks')", "icon('reward')"):
        assert token in dashboard
    assert "nav_link('/admin/dashboard','Огляд','dashboard'" in base
    assert "nav_link('/admin/quick-xp','Швидкі XP','xp'" in base


def test_v12031_transient_alerts_use_toast_source_without_hiding_persistent_warnings():
    account = read("app/web/templates/account_security.html")
    rewards = read("app/web/templates/rewards.html")
    assert 'alert danger" data-toast-source' in account
    assert 'alert success" data-toast-source' in account
    assert 'alert success" data-toast-source' in rewards
    assert "Для суперадміністратора двоетапний вхід" in account
