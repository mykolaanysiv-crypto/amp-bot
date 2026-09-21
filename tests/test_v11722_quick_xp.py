from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v11722_version_and_schema_are_present():
    assert read("VERSION.txt").strip() == "1.17.2.2"
    assert read("VERSION_CHECK.txt").strip() == "1.17.2.2"
    migration = read("migrations/versions/20260921_0011_quick_xp.py")
    assert 'revision: str = "20260921_0011"' in migration
    assert 'down_revision: Union[str, None] = "20260920_0010"' in migration
    assert '"quick_xp_challenges"' in migration
    assert '"quick_xp_completions"' in migration
    assert 'uq_quick_xp_challenge_user' in migration


def test_quick_xp_bot_and_admin_integration_exists():
    handler = read("app/handlers/quick_xp.py")
    assert 'F.text == "⚡ Заробити XP"' in handler
    assert 'quickxp_answer:' in handler
    assert 'QuickXPState.comment' in handler
    assert '⚡ Ще способи заробити XP' in handler
    assert 'quickxp:done' in handler
    keyboard = read("app/keyboards.py")
    assert 'KeyboardButton(text="⚡ Заробити XP")' in keyboard
    assert '("⚡ Заробити XP", "ux:join:quickxp")' in keyboard
    home = read("app/handlers/participant_home.py")
    assert 'Швидкі XP:' in home
    assert 'Натисни «⚡ Заробити XP»' in home
    factory = read("app/web/factory.py")
    assert 'quick_xp as quick_xp_routes' in factory
    assert 'quick_xp_routes' in factory
    template = read("app/web/templates/quick_xp.html")
    assert 'Створити швидке завдання' in template
    assert 'Розіслати невиконавшим' in template


def test_quick_xp_has_caps_and_idempotency():
    service = read("app/quick_xp.py")
    assert 'QUICK_XP_WEEKLY_CAP = 15' in service
    assert 'category="quick_xp"' in service
    assert 'QuickXPCompletion.challenge_id == challenge.id' in service
    assert 'IntegrityError' in service
    model = read("app/model_domains/engagement.py")
    assert 'UniqueConstraint("challenge_id", "user_id", name="uq_quick_xp_challenge_user")' in model
