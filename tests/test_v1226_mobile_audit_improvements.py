"""Source-contract tests for responsive UX changes (no production DB required)."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")

def test_shared_icon_has_explicit_collapse_arrow():
    icons=read('app/web/templates/_ui_macros.html')
    assert "name == 'chevron-left'" in icons
    assert 'm15 6-6 6 6 6' in icons
    assert "icon('chevron-left')" in read('app/web/templates/base.html')

def test_mobile_bell_and_desktop_badges_have_single_fetch_and_sync():
    shell=read('app/web/templates/base.html')
    js=read('app/web/static/web_inbox.js')
    assert shell.count('data-web-unread') == 2
    assert 'querySelectorAll' in js
    assert 'badges.forEach' in js
    assert js.count("fetch('/admin/web-inbox/count'") == 1

def test_mobile_accessible_drawer_and_escape_and_focus():
    js=read('app/web/static/app_shell.js')
    assert "sidebar.setAttribute('role', 'dialog')" in js
    assert "sidebar.removeAttribute('role')" in js
    assert "mobile-nav-open" in js
    assert 'trapSidebarFocus' in js

def test_audit_is_paginated_searchable_and_read_only():
    route=read('app/web/routes/system.py')
    template=read('app/web/templates/audit.html')
    assert 'guard_permission(request, "audit.view")' in route
    assert 'page_size = 40' in route
    assert 'select(func.count())' in route
    assert 'AuditLog.action.ilike' in route
    assert 'name="q"' in template
    assert 'data-label="Дата"' in template
    assert 'audit_pages' in template
    assert 'role="status"' in template

def test_canonical_component_sources_loaded_and_bundled():
    builder=read('scripts/build_admin_css.py')
    bundle=read('app/web/static/admin.css')
    for component in ['styles/components/controls.css','styles/components/navigation.css','styles/components/tables.css','styles/themes/dark.css','styles/responsive.css']:
        assert component in builder
        assert (ROOT/'app/web/static'/component).is_file()
        assert component in bundle
    assert '--color-sidebar:#101b2d' in bundle
