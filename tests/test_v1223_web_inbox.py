"""Source and version regression checks for the account-scoped web inbox."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def test_account_scoped_read_receipts_and_migration():
    model = (ROOT / 'app/model_domains/communications.py').read_text()
    migration = (ROOT / 'migrations/versions/20261011_0019_web_notification_reads.py').read_text()
    assert 'class WebNotificationRead(Base)' in model
    assert 'uq_web_notification_read' in model
    assert '20261010_0018' in migration
    assert 'web_notification_reads' in migration


def test_inbox_is_not_telegram_delivery_status():
    routes = (ROOT / 'app/web/routes/notifications.py').read_text()
    assert 'account.linked_user_id' in routes
    assert 'WebNotificationRead.account_id == account.id' in routes
    assert 'recipient_user_id == account.linked_user_id' in routes
    assert 'guard(request)' in routes
    assert '/admin/web-inbox/count' in routes
    assert '/admin/web-inbox/{notification_id}/read' in routes
    assert 'Notification.status == "sent"' not in routes.split('async def _web_inbox_query')[1].split('@router.get("/admin/notifications"')[0]


def test_readable_and_accessible_badge():
    html = (ROOT / 'app/web/templates/base.html').read_text()
    js = (ROOT / 'app/web/static/web_inbox.js').read_text()
    inbox = (ROOT / 'app/web/templates/web_inbox.html').read_text()
    assert 'data-web-unread hidden' in html
    assert 'count > 99' in js
    assert 'aria-label' in js
    assert 'name="_csrf"' in inbox
    assert 'Позначити прочитаним' in inbox
