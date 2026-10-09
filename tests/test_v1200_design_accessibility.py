from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v1200_version_schema_and_cache_tokens_are_synchronized():
    assert read("VERSION.txt").strip() == "1.20.0"
    assert read("VERSION_CHECK.txt").strip() == "1.20.0"
    assert '"1.20.0"' in read("app/version.py")
    assert 'revision: str = "20261008_0017"' in read("migrations/versions/20261008_0017_media_storage_lifecycle.py")
    for template in ("base.html", "login.html", "login_2fa.html", "login_passkey.html", "account_security.html"):
        assert "v=1.20.0" in read(f"app/web/templates/{template}")


def test_app_shell_has_collapsible_desktop_and_accessible_mobile_drawer():
    base = read("app/web/templates/base.html")
    js = read("app/web/static/app_shell.js")
    for token in (
        'data-sidebar-collapse', 'data-mobile-menu', 'data-sidebar-backdrop',
        'aria-controls="adminSidebar"', 'aria-expanded="false"', 'skip-link',
        'id="main-content"', 'aria-label="Основна навігація"',
    ):
        assert token in base
    for token in (
        "amp-sidebar-collapsed", "localStorage", "sidebar-collapsed", "focusableInSidebar",
        "trapSidebarFocus", "event.key === 'Escape'", "mobileReturnFocus", "nav-open",
    ):
        assert token in js
    assert "onclick=" not in base


def test_design_system_is_tokenized_modular_and_bundle_is_reproducible():
    admin = read("app/web/static/admin.css")
    for name in ("tokens.css", "base.css", "layout.css", "components.css", "utilities.css"):
        assert f"===== {name} =====" in admin
        assert (ROOT / "app/web/static" / name).exists()
    tokens = read("app/web/static/tokens.css")
    for token in (
        "--color-primary", "--color-background", "--color-surface", "--color-text",
        "--color-focus", "--space-4", "--radius-lg", "--sidebar-expanded",
    ):
        assert token in tokens
    assert "prefers-reduced-motion" in read("app/web/static/base.css")
    assert "focus-visible" in read("app/web/static/base.css")
    assert "scripts/build_admin_css.py" in read("BUILD_MANIFEST_V1200.txt")


def test_permission_aware_navigation_and_security_semantics_remain_server_side():
    base = read("app/web/templates/base.html")
    for permission in (
        'has_permission("analytics.view")', 'has_permission("participants.view")',
        'has_permission("events.edit")', 'has_permission("security.manage")',
    ):
        assert permission in base
    assert "is_superadmin" in base
    assert 'action="/admin/logout" method="post"' in base
    assert 'name="_csrf"' in base


def test_auth_surfaces_keep_2fa_passkey_and_accessible_labels():
    login = read("app/web/templates/login.html")
    mfa = read("app/web/templates/login_2fa.html")
    passkey = read("app/web/templates/login_passkey.html")
    assert 'autocomplete="username"' in login and 'autocomplete="current-password"' in login
    assert 'autocomplete="one-time-code"' in mfa and 'aria-describedby="otp-help"' in mfa
    assert "Touch ID" in passkey and "Telegram-код" in passkey
    assert 'data-passkey-auth' in passkey and '/admin/login/passkey/fallback' in passkey


def test_templates_parse_after_design_refactor():
    env = Environment()
    for path in sorted((ROOT / "app/web/templates").glob("*.html")):
        env.parse(path.read_text(encoding="utf-8"))


def test_csp_nonce_architecture_is_preserved_for_scripts():
    base = read("app/web/templates/base.html")
    middleware = read("app/web/security_middleware.py")
    assert 'nonce="{{ request.state.csp_nonce }}"' in base
    assert '/static/app_shell.js?v=1.20.0' in base
    assert '/static/admin_forms.js?v=1.20.0' in base
    assert "unsafe-eval" not in base
    assert "content-security-policy" in middleware
    assert "csp_nonce" in middleware


def test_media_security_and_admin_centers_are_still_present():
    base = read("app/web/templates/base.html")
    assert "nav_link('/admin/media-integrity','Медіа','media'" in base
    assert "nav_link('/admin/security-center','Security Center','shield'" in base
    assert "nav_link('/admin/data-integrity','Цілісність даних','integrity'" in base
    media = read("app/web/templates/media_integrity.html")
    for token in ("Кандидати на карантин", "Глибока перевірка checksum", "hard-delete", "Cloudflare R2"):
        assert token in media
