from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v182_version_and_css_cache_buster():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "1.10.3"
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == "1.10.3"
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "/static/admin.css?v=1.10.3" in base


def test_participant360_quests_and_activities_are_separate_tabs():
    template = (ROOT / "app/web/templates/user_detail.html").read_text(encoding="utf-8")
    assert 'data-tab="quests">🎯 Квести' in template
    assert 'data-tab="activities">⚡ Активності' in template
    assert 'data-panel="quests"' in template
    assert 'data-panel="activities"' in template
    assert 'data-tab="activity">Активність' not in template
    assert 'data-panel="activity"' not in template


def test_participant360_kpis_are_compact_four_column_grid():
    css = (ROOT / "app/web/static/admin.css").read_text(encoding="utf-8")
    assert ".participant360-kpis{" in css
    assert "display:grid!important" in css
    assert "grid-template-columns:repeat(4,minmax(0,1fr))!important" in css
    assert ".participant360-kpis .kpi" in css
    assert "text-align:center" in css


def test_participant360_tables_are_centered_and_safe_from_overlap():
    template = (ROOT / "app/web/templates/user_detail.html").read_text(encoding="utf-8")
    css = (ROOT / "app/web/static/admin.css").read_text(encoding="utf-8")
    assert template.count('class="p360-data-table"') == 2
    assert ".participant360-card .p360-panel th," in css
    assert ".participant360-card .p360-panel td{" in css
    assert "overflow-x:auto" in css
    assert ".p360-data-table" in css


def test_duplicate_xp_history_block_removed_but_xp_tools_remain():
    template = (ROOT / "app/web/templates/user_detail.html").read_text(encoding="utf-8")
    assert "🧾 Останні операції з досвідом" not in template
    assert 'data-panel="xp"' in template
    assert "⚡ Нарахувати досвід" in template
    assert 'action="/admin/users/{{ user.id }}/xp"' in template
