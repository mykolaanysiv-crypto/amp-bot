from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(path):return (ROOT/path).read_text(encoding='utf-8')
def test_styles_are_generated_as_one_asset():
    page=read('app/web/templates/base.html')
    bundle=read('app/web/static/admin.css')
    for name in ('ui_refinement_1221.css','ux_release_1224.css','ux_hotfix_operations.css','ux22_modals.css'):
        assert name in read('scripts/build_admin_css.py')
        assert f'/static/{name}?v=' not in page
        assert f'===== {name} =====' in bundle
    assert 'design_system_v2.css' in bundle
def test_csp_safe_theme_early_init():
    page=read('app/web/templates/base.html')
    assert '/static/theme_init.js?v=1.22.6' in page
    assert '<script>try' not in page
    js=read('app/web/static/app_shell.js')
    assert "['light', 'dark', 'system']" in js
    assert "systemDark?.addEventListener?.('change'" in js
def test_dark_mode_tokens_and_mobile_rules():
    css=read('app/web/static/design_system_v2.css')
    assert '--ui-bg:#0b1220' in css
    assert '@media(max-width:430px)' in css
    assert 'prefers-reduced-motion:reduce' in css
