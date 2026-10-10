from __future__ import annotations

from pathlib import Path
import re

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1202_version_schema_and_no_new_migration():
    assert read("VERSION.txt").strip() == "1.20.3"
    assert read("VERSION_CHECK.txt").strip() == "1.20.3"
    assert 'revision: str = "20261010_0018"' in read("migrations/versions/20261010_0018_web_user_profiles.py")
    assert not any("0019" in p.name for p in (ROOT / "migrations/versions").glob("*.py"))


def test_account_uses_real_tabs_not_anchor_scroll():
    account = read("app/web/templates/account_security.html")
    interaction = read("app/web/static/interaction.js")
    for token in (
        'role="tablist"', 'role="tab"', 'role="tabpanel"',
        'data-tab="profile"', 'data-tab="achievements"', 'data-tab="security"', 'data-tab="sessions"',
        'data-tab-panel="profile"', 'data-tab-panel="security"', 'data-tabs-key="tab"',
    ):
        assert token in account
    for forbidden in ('href="#profile"', 'href="#achievements"', 'href="#security"', 'href="#sessions"'):
        assert forbidden not in account
    for token in ("ArrowRight", "ArrowLeft", "Home", "End", "URLSearchParams", "history.replaceState"):
        assert token in interaction


def test_profile_and_avatar_editing_are_dialogs_with_motion_and_preview():
    account = read("app/web/templates/account_security.html")
    css = read("app/web/static/interaction.css")
    js = read("app/web/static/interaction.js")
    for token in ('id="profileEditDialog"', 'id="avatarDialog"', 'data-avatar-input', 'data-avatar-preview'):
        assert token in account
    for token in ("amp-dialog-in", "amp-backdrop-in", "--motion-base", "prefers-reduced-motion"):
        assert token in css
    assert "URL.createObjectURL" in js


def test_sidebar_identity_is_compact_avatar_aware_and_account_dropdown_is_single_entrypoint():
    base = read("app/web/templates/base.html")
    dependencies = read("app/web/dependencies.py")
    auth = read("app/web/auth_routes.py")
    assert 'admin_avatar_path' in dependencies
    assert 'request.session["admin_avatar_path"]' in auth
    assert 'data-account-menu-button' in base and 'data-account-menu' in base
    assert 'class="sidebar-avatar"' in base and 'admin_avatar_path' in base
    assert "nav_link('/admin/account','Мій кабінет'" not in base
    assert 'href="/admin/account?tab=profile"' in base


def test_base_shell_uses_csp_safe_dataset_not_inline_javascript_config():
    base = read("app/web/templates/base.html")
    shell = read("app/web/static/app_shell.js")
    assert 'data-csrf-token="{{ csrf_token }}"' in base
    assert "window.AMP_UI" not in base
    assert '<script nonce="{{ request.state.csp_nonce }}">' not in base
    assert "document.body.dataset.csrfToken" in shell


def test_participant_linking_is_searchable_superadmin_picker():
    tpl = read("app/web/templates/security_accounts.html")
    auth = read("app/web/auth_routes.py")
    js = read("app/web/static/interaction.js")
    assert 'data-participant-combobox' in tpl
    assert 'role="combobox"' in tpl
    assert 'name="linked_user_id"' in tpl
    assert '@router.get("/admin/security/participant-search")' in auth
    search_block = auth[auth.index('@router.get("/admin/security/participant-search")'):]
    assert 'guard_superadmin(request)' in search_block[:600]
    assert 'User.permanent_deleted_at.is_(None)' in search_block
    assert '/admin/security/participant-search?q=' in js


def test_help_center_uses_category_tabs_and_search_remains_cross_category():
    tpl = read("app/web/templates/help.html")
    experience = read("app/web/static/experience.js")
    interaction = read("app/web/static/interaction.js")
    assert 'data-help-category-filter="events"' in tpl
    assert 'data-help-category="security"' in tpl
    assert 'data-help-category="media"' in tpl
    assert 'data-help-search' in tpl
    assert "query ? haystack.includes(query) : categoryMatch" in experience
    assert "data-help-category-filter" in interaction


def test_unified_system_icon_policy_removes_literal_emoji_from_web_templates():
    # User-generated DB content remains untouched; this only checks system-authored template glyphs.
    emoji = re.compile(r"[\U0001F000-\U0001FAFF]|[⚙⚠⚡⛔✅✕❌✏➕✔✖❄☑☒☀☁☂☃★☆♥♦♣♠]")
    offenders = []
    for path in sorted((ROOT / "app/web/templates").glob("*.html")):
        if emoji.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == []
    macros = read("app/web/templates/_ui_macros.html")
    for name in ("user", "badge", "shield", "activity", "edit", "camera", "trash", "calendar", "idea", "chevron-down"):
        assert f"name == '{name}'" in macros


def test_interaction_layer_has_motion_hover_toasts_and_contrast_guards():
    css = read("app/web/static/interaction.css")
    js = read("app/web/static/interaction.js")
    for token in ("--motion-fast", "--motion-base", "--motion-slow", ".card:hover", ".amp-toast", ".amp-tab-indicator", ".account-menu"):
        assert token in css
    for token in ("data-toast-region", "aria-selected", "data-account-menu-button", "data-avatar-input"):
        assert token in js or token in read("app/web/templates/base.html")
    assert "rgba(255,255,255,.86)" in css


def test_calendar_and_idea_detail_use_svg_icon_system_and_no_inline_calendar_js():
    cal = read("app/web/templates/calendar.html")
    adminux = read("app/web/routes/adminux.py")
    idea = read("app/web/templates/idea_detail.html")
    assert "{{ icon(item.icon) }}" in cal
    assert "onclick=" not in cal
    assert 'add_item(e.starts_at, "calendar"' in adminux
    assert "icon('compass')" in idea and "icon('trash')" in idea



def test_all_web_templates_are_free_of_inline_executable_js_and_event_handlers():
    templates = sorted((ROOT / "app/web/templates").glob("*.html"))
    event_attr = re.compile(r"\s(?:onclick|onchange|oninput|onsubmit|onload|onkeydown|onkeyup)=", re.I)
    script = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.I | re.S)
    offenders = []
    for path in templates:
        source = path.read_text(encoding="utf-8")
        if event_attr.search(source):
            offenders.append(f"{path.name}:inline-handler")
        for match in script.finditer(source):
            if "src=" not in match.group("attrs"):
                offenders.append(f"{path.name}:inline-script")
    assert offenders == []
    base = read("app/web/templates/base.html")
    assert '/static/page_behaviors.js?v=1.20.3' in base
    for rel in (
        "app/web/static/page_behaviors.js",
        "app/web/static/event_detail.js",
        "app/web/static/telegram_event_scanner.js",
        "app/web/static/analytics.js",
        "app/web/static/analytics_detail.js",
    ):
        assert (ROOT / rel).exists(), rel


def test_v1202_templates_parse():
    env = Environment()
    for path in sorted((ROOT / "app/web/templates").glob("*.html")):
        env.parse(path.read_text(encoding="utf-8"))
