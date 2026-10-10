from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1201_version_and_additive_profile_migration():
    assert read("VERSION.txt").strip() == "1.20.2"
    assert read("VERSION_CHECK.txt").strip() == "1.20.2"
    migration = read("migrations/versions/20261010_0018_web_user_profiles.py")
    assert 'revision: str = "20261010_0018"' in migration
    assert 'down_revision: Union[str, None] = "20261008_0017"' in migration
    for token in ("profile_title", "profile_bio", "profile_email", "profile_phone", "avatar_path", "linked_user_id"):
        assert token in migration
    assert "def downgrade" in migration


def test_web_staff_profile_model_and_avatar_privacy_are_explicit():
    identity = read("app/model_domains/identity.py")
    security = read("app/security.py")
    for token in ("profile_title", "profile_bio", "profile_email", "profile_phone", "avatar_path", "linked_user_id"):
        assert token in identity
    assert "profile_bio: Mapped[str | None] = mapped_column(EncryptedText()" in identity
    assert "profile_email: Mapped[str | None] = mapped_column(EncryptedText()" in identity
    assert "profile_phone: Mapped[str | None] = mapped_column(EncryptedText()" in identity
    assert '"staff_profiles"' in security


def test_profile_routes_are_self_service_but_linking_is_superadmin_only():
    auth = read("app/web/auth_routes.py")
    assert '@router.post("/admin/account/profile"' in auth
    assert '@router.post("/admin/account/avatar"' in auth
    assert '@router.post("/admin/account/avatar/remove"' in auth
    assert 'save_image(avatar, "staff_profiles")' in auth
    assert "web_profile_updated" in auth and "web_profile_avatar_updated" in auth
    link_pos = auth.index('@router.post("/admin/security/accounts/{account_id}/profile-link")')
    link_block = auth[link_pos:link_pos + 1800]
    assert "guard_superadmin(request)" in link_block
    assert "web_profile_link_updated" in link_block


def test_cabinet_has_avatar_bio_badges_stats_security_and_modal_editing():
    account = read("app/web/templates/account_security.html")
    for token in (
        "Мій кабінет", "profileEditDialog", "avatarDialog", "profile_bio", "profile_email",
        "profile_phone", "badge-gallery", "profile_stats", "Passkey", "Активні сесії", 'data-profile-theme="system"',
    ):
        assert token in account
    assert 'data-modal-open="profileEditDialog"' in account
    assert 'data-modal-open="avatarDialog"' in account


def test_help_center_is_searchable_and_covers_core_workflows():
    help_tpl = read("app/web/templates/help.html")
    for token in (
        "Центр допомоги", "data-help-search", "Події", "Квести", "Бейджі", "Мій кабінет",
        "Security Center", "Media Integrity", "2FA", "Passkey", "FAQ", "ЩО НОВОГО",
    ):
        assert token in help_tpl


def test_visual_experience_has_brand_depth_dialogs_motion_and_safe_limits():
    css = read("app/web/static/experience.css")
    tokens = read("app/web/static/tokens.css")
    for token in ("--gradient-brand", "--gradient-energy", "--color-accent-cyan", "--color-accent-lime"):
        assert token in tokens
    for token in (
        ".amp-modal", ".profile-hero", ".help-hero", ".dashboard-experience-hero",
        ".page-shell{width:min(100%,1480px)", "prefers-reduced-motion",
    ):
        assert token in css


def test_experience_js_is_csp_safe_progressive_enhancement():
    js = read("app/web/static/experience.js")
    base = read("app/web/templates/base.html")
    for token in ("data-modal-open", "data-modal-close", "confirmMessage", "showModal", "data-help-search", "edit-action-button"):
        assert token in js
    all_templates = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app/web/templates").glob("*.html"))
    assert "data-confirm-message" in all_templates
    assert '/static/experience.js?v=1.20.2' in base
    assert "eval(" not in js
    assert "new Function" not in js


def test_new_templates_parse_with_jinja():
    env = Environment()
    for rel in ("app/web/templates/base.html", "app/web/templates/account_security.html", "app/web/templates/help.html", "app/web/templates/security_accounts.html", "app/web/templates/dashboard.html"):
        env.parse(read(rel))


def test_editing_and_destructive_flows_do_not_use_browser_prompt_confirm():
    templates = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app/web/templates").glob("*.html"))
    for forbidden in ("window.confirm", "window.prompt", 'onclick="return confirm', 'onsubmit="return confirm'):
        assert forbidden not in templates
    assert 'id="attendanceOverrideDialog"' in templates
    assert 'data-confirm-message=' in templates
