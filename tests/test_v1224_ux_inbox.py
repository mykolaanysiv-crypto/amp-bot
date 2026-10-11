"""Regression gates for the issues reported in AMP XP v1.22.3 screenshots."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding='utf8')

def test_only_one_notification_bell_in_topbar():
    markup = read('app/web/templates/base.html')
    assert markup.count('web-inbox-bell') == 1
    assert 'href="/admin/notifications" aria-label="Відкрити центр сповіщень"' not in markup

def test_existing_reset_not_duplicated_by_js():
    js = read('app/web/static/app_shell.js')
    assert "form.querySelector('[data-filter-reset],.filter-reset,.event-filter-reset,.filter-actions a[href]')" in js

def test_sidebar_indicator_tracks_collapsed_state():
    base = read('app/web/templates/base.html')
    css = read('app/web/static/ux_release_1224.css')
    assert "icon('chevron-left')" in base
    assert 'body.sidebar-collapsed .sidebar-collapse .sidebar-collapse-icon{transform:rotate(180deg)}' in css

def test_bulk_read_account_scoped_and_csrf_form():
    route = read('app/web/routes/notifications.py')
    template = read('app/web/templates/web_inbox.html')
    assert '/admin/web-inbox/read-all' in route
    assert 'on_conflict_do_nothing(constraint="uq_web_notification_read")' in route
    assert 'WebStaffAccount.linked_user_id' in route
    assert 'Notification.recipient_user_id' in route
    assert 'name="_csrf"' in template
    assert 'Позначити всі як прочитані' in template

def test_release_styles_loaded():
    assert f'/static/ux_release_1224.css?v={read("VERSION.txt").strip()}' in read('app/web/templates/base.html')
