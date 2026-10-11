from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v1210_version_and_schema_baseline():
    assert read("VERSION.txt").strip() == "1.21.0"
    assert read("VERSION_CHECK.txt").strip() == "1.21.0"
    assert '"1.21.0"' in read("app/version.py")
    migrations = read("scripts/release_consistency_check.py")
    assert 'EXPECTED_ALEMBIC_HEAD = "20261010_0018"' in migrations


def test_role_aware_navigation_preserves_management_and_system_tools():
    base = read("app/web/templates/base.html")
    for token in (
        "Робочий простір",
        "Адміністрування",
        "Система",
        "Підтримка",
        "data-role-navigation",
        "is_management_ui",
        "is_system_ui",
    ):
        assert token in base
    for route in (
        "/admin/security-center",
        "/admin/media-integrity",
        "/admin/operations",
        "/admin/audit",
        "/admin/system-health",
        "/admin/security",
        "/admin/settings",
        "/admin/reports",
        "/admin/broadcasts",
        "/admin/notifications",
    ):
        assert route in base


def test_role_context_is_permission_aware_and_future_participant_safe():
    dependencies = read("app/web/dependencies.py")
    for token in (
        "is_management_ui",
        "is_participant_ui",
        "is_system_ui",
        "permissions.intersection(system_permissions)",
    ):
        assert token in dependencies
    assert '"has_permission": lambda permission: has_web_permission(request, permission)' in dependencies


def test_dashboard_is_product_first_but_keeps_admin_diagnostics():
    dashboard = read("app/web/templates/dashboard.html")
    for token in (
        "Огляд простору",
        "product-kpi-grid",
        "Найближчі події",
        "Сповіщення та важливе",
        "Робота команди",
        "Стан платформи",
        "Конверсія відгуків",
        "Шлях залучення до участі",
        "Канонічний довідник",
    ):
        assert token in dashboard


def test_events_creation_uses_accessible_dialog_instead_of_inline_create_block():
    events = read("app/web/templates/events.html")
    assert 'data-modal-open="createEventDialog"' in events
    assert 'id="createEventDialog"' in events
    assert 'class="amp-modal amp-editor-modal event-create-dialog"' in events
    assert 'action="/admin/events/create"' in events
    assert 'event-create-card' not in events


def test_registrations_workspace_uses_compact_semantic_actions():
    tpl = read("app/web/templates/registrations.html")
    for token in (
        "product-table",
        "participant-cell",
        "product-row-actions",
        "row-icon-success",
        "row-icon-danger",
        "Очікують підтвердження",
    ):
        assert token in tpl
    assert 'action="/admin/users/{{u.id}}/activate"' in tpl
    assert 'action="/admin/registrations/{{u.id}}/reject"' in tpl


def test_ideas_use_discovery_layout_and_keep_opportunities_separate():
    tpl = read("app/web/templates/ideas.html")
    assert "Ідеї, що стають діями" in tpl
    assert "discovery-grid" in tpl
    assert "/admin/opportunities" in tpl
    assert "idea.result_image_path" in tpl


def test_product_experience_css_has_readability_motion_and_responsive_guards():
    css = read("app/web/static/product_experience.css")
    for token in (
        "--px-teal-950",
        ".product-hero",
        ".product-kpi-grid",
        ".product-admin-zone",
        ".product-system-zone",
        "word-break:normal",
        "hyphens:none",
        "prefers-reduced-motion",
        "backdrop-filter",
    ):
        assert token in css
    assert '"product_experience.css"' in read("scripts/build_admin_css.py")


def test_product_redesign_does_not_reintroduce_inline_js():
    import re
    event_attr = re.compile(r"\s(?:onclick|onchange|oninput|onsubmit|onload|onkeydown|onkeyup)=", re.I)
    script = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.I | re.S)
    offenders = []
    for path in sorted((ROOT / "app/web/templates").glob("*.html")):
        source = path.read_text(encoding="utf-8")
        if event_attr.search(source):
            offenders.append(f"{path.name}:handler")
        for match in script.finditer(source):
            if "src=" not in match.group("attrs"):
                offenders.append(f"{path.name}:inline-script")
    assert offenders == []
