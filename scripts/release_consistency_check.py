from __future__ import annotations

from pathlib import Path
import re

from scripts.dependency_lock_check import file_sha256, validate_dependency_locks

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.20.2"
EXPECTED_ALEMBIC_HEAD = "20261010_0018"
EXPECTED_PYTHON = "3.13"
EXPECTED_POSTGRES = "18"

CRITICAL_RUNTIME_FILES = (
    "run.py",
    "run_web.py",
    "app/main.py",
    "app/bot_runtime.py",
    "app/web/factory.py",
    "app/web/lifespan.py",
    "app/web/auth_routes.py",
    "app/web/security_middleware.py",
    "app/web/routes/security_center.py",
    "app/web/routes/media_integrity.py",
    "app/web/static/passkeys.js",
    "app/web/static/admin_forms.js",
    "app/web/static/app_shell.js",
    "app/web/static/experience.js",
    "app/web/static/experience.css",
    "app/web/static/interaction.js",
    "app/web/static/page_behaviors.js",
    "app/web/static/event_detail.js",
    "app/web/static/telegram_event_scanner.js",
    "app/web/static/analytics.js",
    "app/web/static/analytics_detail.js",
    "app/web/static/interaction.css",
    "app/web/static/admin.css",
    "app/web/static/tokens.css",
    "app/web/static/base.css",
    "app/web/static/layout.css",
    "app/web/static/components.css",
    "app/web/static/utilities.css",
    "app/web/templates/base.html",
    "app/web/templates/_ui_macros.html",
    "app/passkeys.py",
    "app/rate_limit.py",
    "app/metrics.py",
    "app/observability_snapshot.py",
    "app/security_center.py",
    "app/domain_services/quest_auto.py",
    "migrations/versions/20261007_0016_security_observability.py",
    "migrations/versions/20261008_0017_media_storage_lifecycle.py",
    "migrations/versions/20261010_0018_web_user_profiles.py",
    "app/media_storage.py",
    "app/media_integrity.py",
    "scripts/migrate_media_storage.py",
    "scripts/build_admin_css.py",
    "scripts/heroku_release.py",
    "scripts/startup_smoke.py",
    "scripts/schema_drift_check.py",
    "scripts/verify_backup_restore.sh",
    "tests/test_v1200_design_accessibility.py",
    "tests/test_v1201_visual_experience_profiles.py",
    "tests/test_v1202_ui_polish_interaction.py",
    "tests/js/test_app_shell.js",
    "tests/js/test_experience.js",
    "tests/js/test_interaction.js",
    "tests/js/test_csp_externalization.js",
    ".github/workflows/ci.yml",
    ".github/workflows/backup.yml",
)


def _alembic_head(root: Path) -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    rev_re = re.compile(r'^revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', re.M)
    down_re = re.compile(r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:["\']([^"\']+)["\']|None)', re.M)
    for path in (root / "migrations" / "versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = rev_re.search(text)
        down = down_re.search(text)
        if rev:
            revisions.add(rev.group(1))
        if down and down.group(1):
            parents.add(down.group(1))
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise SystemExit(f"Expected one Alembic head, found {heads}")
    return heads[0]


def validate_release_consistency(root: Path = ROOT) -> None:
    hashes = validate_dependency_locks(root)
    version = (root / "VERSION.txt").read_text(encoding="utf-8").strip()
    version_check = (root / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip()
    if version != EXPECTED_VERSION or version_check != EXPECTED_VERSION:
        raise SystemExit(f"Version mismatch: VERSION={version!r}, VERSION_CHECK={version_check!r}")

    app_version_source = (root / "app" / "version.py").read_text(encoding="utf-8")
    if f'"{EXPECTED_VERSION}"' not in app_version_source:
        raise SystemExit("app/version.py fallback is not synchronized")

    head = _alembic_head(root)
    if head != EXPECTED_ALEMBIC_HEAD:
        raise SystemExit(f"Alembic head mismatch: expected {EXPECTED_ALEMBIC_HEAD}, got {head}")

    docs = {
        "README.md": (EXPECTED_VERSION, EXPECTED_ALEMBIC_HEAD),
        "HEROKU_DEPLOY.md": (EXPECTED_VERSION, EXPECTED_ALEMBIC_HEAD),
        "BUILD_MANIFEST_V1202.txt": (EXPECTED_VERSION, EXPECTED_ALEMBIC_HEAD, EXPECTED_PYTHON, EXPECTED_POSTGRES),
        "RELEASE_V1202_UA.md": (EXPECTED_VERSION, EXPECTED_ALEMBIC_HEAD),
        "AUDIT_UI_V1202_UA.md": (EXPECTED_VERSION,),
        "DESIGN_SYSTEM_V1202.md": (EXPECTED_VERSION,),
        "INTERACTION_SYSTEM_V1202.md": (EXPECTED_VERSION,),
        "ACCESSIBILITY_V1202.md": ("WCAG 2.2 AA", EXPECTED_VERSION),
        "UI_VISUAL_CHECKLIST_V1202.md": (EXPECTED_VERSION,),
        "COMMANDS_V1202.txt": (EXPECTED_VERSION,),
        "TEST_REPORT_V1202.txt": (EXPECTED_VERSION,),
    }
    for name, tokens in docs.items():
        path = root / name
        if not path.exists():
            raise SystemExit(f"Release documentation missing: {name}")
        text = path.read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            raise SystemExit(f"{name} is not synchronized; missing {missing}")

    manifest = (root / "BUILD_MANIFEST_V1202.txt").read_text(encoding="utf-8")
    for lock_name, digest in hashes.items():
        token = f"{lock_name} SHA256: {digest}"
        if token not in manifest:
            raise SystemExit(f"Build manifest lock fingerprint mismatch: {lock_name}")
    for relative in CRITICAL_RUNTIME_FILES:
        if not (root / relative).exists():
            raise SystemExit(f"Required runtime file missing: {relative}")
        if relative not in manifest:
            raise SystemExit(f"Build manifest does not list critical runtime file: {relative}")

    docker = (root / "Dockerfile").read_text(encoding="utf-8")
    if "FROM python:3.13-slim" not in docker or "-r requirements.lock" not in docker:
        raise SystemExit("Docker runtime/lock installation is not reproducible")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    if "public.ecr.aws/docker/library/postgres:18-alpine" not in compose:
        raise SystemExit("docker-compose PostgreSQL must match PostgreSQL 18 baseline")

    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    required_ci = (
        "pip install -r requirements-dev.lock",
        "python -m scripts.dependency_lock_check",
        "python -m scripts.release_consistency_check",
        "node tests/js/test_admin_forms.js",
        "node tests/js/test_app_shell.js",
        "node tests/js/test_experience.js",
        "node tests/js/test_interaction.js",
        "node tests/js/test_csp_externalization.js",
        "node --check app/web/static/page_behaviors.js",
        "pip-audit -r requirements.lock --progress-spinner=off",
        "pip check",
        "image: public.ecr.aws/docker/library/postgres:18",
        "Post-deploy readiness and version smoke",
        "Restore-verify fresh pre-deploy backup",
    )
    for token in required_ci:
        if token not in ci:
            raise SystemExit(f"CI release gate missing: {token}")
    audit_block = ci[ci.index("Dependency vulnerability audit"):ci.index("Installed dependency consistency")]
    if "continue-on-error" in audit_block:
        raise SystemExit("pip-audit must be a blocking release gate")

    for template in ("base.html", "login.html", "login_2fa.html", "login_passkey.html", "account_security.html"):
        text = (root / "app" / "web" / "templates" / template).read_text(encoding="utf-8")
        if f"v={EXPECTED_VERSION}" not in text:
            raise SystemExit(f"Static cache token mismatch in {template}")

    requirements = (root / "requirements.lock").read_text(encoding="utf-8")
    if "webauthn==3.0.1" not in requirements:
        raise SystemExit("v1.19.0 passkey dependency is not locked")

    migration = (root / "migrations" / "versions" / "20261007_0016_security_observability.py").read_text(encoding="utf-8")
    for token in ("web_authn_credentials", 'down_revision: Union[str, None] = "20260925_0015"', "def downgrade"):
        if token not in migration:
            raise SystemExit(f"v1.19.0 additive migration gate missing: {token}")

    migration_1191 = (root / "migrations" / "versions" / "20261008_0017_media_storage_lifecycle.py").read_text(encoding="utf-8")
    for token in ("storage_backend", "checksum_sha256", "lifecycle_state", 'down_revision: Union[str, None] = "20261007_0016"'):
        if token not in migration_1191:
            raise SystemExit(f"v1.19.1 migration gate missing: {token}")


    migration_1201 = (root / "migrations" / "versions" / "20261010_0018_web_user_profiles.py").read_text(encoding="utf-8")
    for token in ("profile_title", "profile_bio", "avatar_path", "linked_user_id", 'down_revision: Union[str, None] = "20261008_0017"', "def downgrade"):
        if token not in migration_1201:
            raise SystemExit(f"v1.20.1 profile migration gate missing: {token}")

    base_template = (root / "app" / "web" / "templates" / "base.html").read_text(encoding="utf-8")
    for token in ("skip-link", "data-sidebar-collapse", "data-mobile-menu", 'id="main-content"', "_ui_macros.html"):
        if token not in base_template:
            raise SystemExit(f"v1.20.2 app-shell gate missing: {token}")
    if "onclick=" in base_template:
        raise SystemExit("v1.20.2 app shell must use CSP-safe event listeners, not inline onclick")
    if "window.AMP_UI" in base_template or "<script nonce=\"{{ request.state.csp_nonce }}\">" in base_template:
        raise SystemExit("v1.20.2 app shell must not embed inline JavaScript configuration")
    if 'data-csrf-token="{{ csrf_token }}"' not in base_template:
        raise SystemExit("v1.20.2 CSP-safe CSRF dataset gate missing")

    # v1.20.2 CSP architecture: every executable script is external and no HTML event handler attributes remain.
    inline_handler_re = re.compile(r"\s(?:onclick|onchange|oninput|onsubmit|onload|onkeydown|onkeyup)=", re.I)
    inline_script_re = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.I | re.S)
    csp_offenders: list[str] = []
    for template_path in sorted((root / "app" / "web" / "templates").glob("*.html")):
        source = template_path.read_text(encoding="utf-8")
        if inline_handler_re.search(source):
            csp_offenders.append(f"{template_path.name}:inline-handler")
        for match in inline_script_re.finditer(source):
            if "src=" not in match.group("attrs"):
                csp_offenders.append(f"{template_path.name}:inline-script")
    if csp_offenders:
        raise SystemExit("v1.20.2 CSP externalization gate failed: " + ", ".join(csp_offenders))

    app_shell = (root / "app" / "web" / "static" / "app_shell.js").read_text(encoding="utf-8")
    for token in ("amp-sidebar-collapsed", "trapSidebarFocus", "mobileReturnFocus", "localStorage", "prefers-color-scheme"):
        if token not in app_shell:
            raise SystemExit(f"v1.20.2 app-shell behavior gate missing: {token}")

    tokens_css = (root / "app" / "web" / "static" / "tokens.css").read_text(encoding="utf-8")
    for token in ("--color-primary", "--color-focus", "--space-4", "--radius-lg", "--sidebar-expanded", "--gradient-brand", "--color-accent-cyan", "--color-accent-lime"):
        if token not in tokens_css:
            raise SystemExit(f"v1.20.2 design token gate missing: {token}")
    if "prefers-reduced-motion" not in (root / "app" / "web" / "static" / "base.css").read_text(encoding="utf-8"):
        raise SystemExit("v1.20.2 reduced-motion accessibility gate missing")

    experience_js = (root / "app" / "web" / "static" / "experience.js").read_text(encoding="utf-8")
    for token in ("data-modal-open", "confirmMessage", "showModal", "amp-theme", "data-help-search", "edit-action-button"):
        if token not in experience_js:
            raise SystemExit(f"v1.20.2 experience behavior gate missing: {token}")
    experience_css = (root / "app" / "web" / "static" / "experience.css").read_text(encoding="utf-8")
    for token in (".amp-modal", ".profile-hero", ".help-hero", ".dashboard-experience-hero", ".page-shell{width:min(100%,1480px)"):
        if token not in experience_css:
            raise SystemExit(f"v1.20.2 visual-experience gate missing: {token}")
    account_template = (root / "app" / "web" / "templates" / "account_security.html").read_text(encoding="utf-8")
    for token in ("profileEditDialog", "avatarDialog", "Мій кабінет", "badge-gallery"):
        if token not in account_template:
            raise SystemExit(f"v1.20.2 web-cabinet gate missing: {token}")
    help_template = (root / "app" / "web" / "templates" / "help.html").read_text(encoding="utf-8")
    for token in ("Центр допомоги", "data-help-search", "2FA", "Media Integrity", "ЩО НОВОГО"):
        if token not in help_template:
            raise SystemExit(f"v1.20.2 Help Center gate missing: {token}")
    security_source = (root / "app" / "security.py").read_text(encoding="utf-8")
    if '"staff_profiles"' not in security_source:
        raise SystemExit("v1.20.2 profile avatars must remain staff-private")
    identity_source = (root / "app" / "model_domains" / "identity.py").read_text(encoding="utf-8")
    for token in (
        "profile_bio: Mapped[str | None] = mapped_column(EncryptedText()",
        "profile_email: Mapped[str | None] = mapped_column(EncryptedText()",
        "profile_phone: Mapped[str | None] = mapped_column(EncryptedText()",
    ):
        if token not in identity_source:
            raise SystemExit(f"v1.20.2 profile privacy gate missing: {token}")

    # v1.20.2 UI Polish, Navigation & Interaction 3.0 guards.
    interaction_js = (root / "app" / "web" / "static" / "interaction.js").read_text(encoding="utf-8")
    interaction_css = (root / "app" / "web" / "static" / "interaction.css").read_text(encoding="utf-8")
    security_accounts_template = (root / "app" / "web" / "templates" / "security_accounts.html").read_text(encoding="utf-8")
    auth_routes = (root / "app" / "web" / "auth_routes.py").read_text(encoding="utf-8")
    for token in ("URLSearchParams", "history.replaceState", "ArrowRight", "ArrowLeft", "data-account-menu-button", "participant-search", "data-avatar-input", "data-help-category-filter"):
        if token not in interaction_js and token not in base_template:
            raise SystemExit(f"v1.20.2 interaction behavior gate missing: {token}")
    for token in ('role="tablist"', 'role="tabpanel"', 'data-tabs-key="tab"', 'data-tab-panel="profile"', 'data-tab-panel="security"', 'data-tab-panel="sessions"'):
        if token not in account_template:
            raise SystemExit(f"v1.20.2 real-tabs gate missing: {token}")
    for forbidden in ('href="#profile"', 'href="#achievements"', 'href="#security"', 'href="#sessions"'):
        if forbidden in account_template:
            raise SystemExit(f"v1.20.2 account tabs must not use anchor scrolling: {forbidden}")
    for token in ('@router.get("/admin/security/participant-search")', "guard_superadmin(request)"):
        if token not in auth_routes:
            raise SystemExit(f"v1.20.2 participant picker security gate missing: {token}")
    for token in ('data-participant-combobox', 'data-combobox-input', 'name="linked_user_id"'):
        if token not in security_accounts_template:
            raise SystemExit(f"v1.20.2 participant combobox gate missing: {token}")
    for token in ("--motion-base", ".amp-tab-indicator", ".account-menu", ".amp-toast", "prefers-reduced-motion"):
        if token not in interaction_css:
            raise SystemExit(f"v1.20.2 interaction style gate missing: {token}")
    if "nav_link('/admin/account','Мій кабінет'" in base_template:
        raise SystemExit("v1.20.2 sidebar must not duplicate the account navigation entry")
    if "admin_avatar_path" not in base_template:
        raise SystemExit("v1.20.2 global avatar rendering gate missing")
    build_css_source = (root / "scripts" / "build_admin_css.py").read_text(encoding="utf-8")
    if '"interaction.css"' not in build_css_source:
        raise SystemExit("v1.20.2 interaction.css is not included in the deterministic CSS bundle")

    # admin.css is a reproducible bundle from modular sources and compatibility CSS.
    from scripts.build_admin_css import build
    current = (root / "app" / "web" / "static" / "admin.css").read_text(encoding="utf-8")
    rebuilt = build()
    if current != rebuilt:
        raise SystemExit("admin.css bundle drifted from modular sources")

    security_middleware = (root / "app" / "web" / "security_middleware.py").read_text(encoding="utf-8")
    for token in ("content-security-policy", "content-security-policy-report-only", "csp_nonce"):
        if token not in security_middleware:
            raise SystemExit(f"CSP gate missing: {token}")

    alembic_ini = (root / "alembic.ini").read_text(encoding="utf-8")
    if "path_separator = os" not in alembic_ini:
        raise SystemExit("Alembic path_separator=os is required to avoid legacy parsing fallback")


def main() -> None:
    validate_release_consistency()
    print(f"Release consistency PASS for AMP v{EXPECTED_VERSION}; Alembic head={EXPECTED_ALEMBIC_HEAD}")


if __name__ == "__main__":
    main()
