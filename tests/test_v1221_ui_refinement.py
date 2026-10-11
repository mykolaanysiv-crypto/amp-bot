"""Dependency-free source regression checks for the v1.22.1 UX refinement."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'app/web/templates'



CURRENT_VERSION = (Path(__file__).resolve().parents[1] / "VERSION.txt").read_text(encoding="utf-8").strip()

def test_semantic_icon_stroke():
    text = (TEMPLATES / '_ui_macros.html').read_text(encoding='utf-8')
    assert '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"' in text
    assert 'stroke-width="1.8"' in text


def test_dashboard_league_top_five_uses_real_query():
    route = (ROOT / 'app/web/routes/dashboard.py').read_text(encoding='utf-8')
    page = (TEMPLATES / 'dashboard.html').read_text(encoding='utf-8')
    assert 'configured_leagues = await runtime_leagues(session)' in route
    assert 'league_for_xp(int(xp), configured_leagues).title' in route
    assert 'top[:5]' in route
    assert 'for id,name,xp,league_name in top_with_leagues' in page


def test_event_filters_paired_with_reset():
    page = (TEMPLATES / 'events.html').read_text(encoding='utf-8')
    css = (ROOT / 'app/web/static/ui_refinement_1221.css').read_text(encoding='utf-8')
    assert 'class="event-filter-actions"' in page
    assert 'href="/admin/events">Скинути' in page
    assert '.event-filter-actions' in css


def test_no_detail_page_duplicate_edit():
    for name in ('quest_detail.html', 'task_detail.html'):
        source = (TEMPLATES / name).read_text(encoding='utf-8')
        assert 'page-edit-button' not in source
        assert 'id="quest-edit"' not in source
        assert 'id="task-edit"' not in source
    # Their catalog forms remain available (and server routes are unchanged).
    for name in ('quests.html', 'tasks.html'):
        assert 'event-edit-details' in (TEMPLATES / name).read_text(encoding='utf-8')


def test_theme_and_motion_tokens():
    css = (ROOT / 'app/web/static/ui_refinement_1221.css').read_text(encoding='utf-8')
    assert 'body[data-theme=dark]' in css
    assert 'prefers-reduced-motion:reduce' in css
    assert '.account-menu' in css


def test_cache_token_and_release_number():
    assert (ROOT / 'VERSION.txt').read_text().strip() == CURRENT_VERSION
    assert (ROOT / 'VERSION_CHECK.txt').read_text().strip() == CURRENT_VERSION
    page = (TEMPLATES / 'base.html').read_text(encoding='utf-8')
    assert f'ui_refinement_1221.css?v={CURRENT_VERSION}' in page
    assert f'data-app-version="{CURRENT_VERSION}"' in page
