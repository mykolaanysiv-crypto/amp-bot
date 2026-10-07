"""v1.19.0 web UI hotfix regression/source gates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_and_asset_tokens_are_synchronized():
    assert read("VERSION.txt").strip() == "1.19.0"
    assert read("VERSION_CHECK.txt").strip() == "1.19.0"
    assert '"1.19.0"' in read("app/version.py")
    for path in ("base.html", "login.html", "login_2fa.html"):
        assert "v=1.19.0" in read(f"app/web/templates/{path}")


def test_quick_xp_answers_are_first_class_and_include_partial_respondents():
    route = read("app/web/routes/quick_xp.py")
    template = read("app/web/templates/quick_xp.html")
    css = read("app/web/static/admin.css")
    assert 'QuickXPAnswer.challenge_id.label("challenge_id")' in route
    assert "response_counts=response_counts" in route
    assert 'href="/admin/quick-xp/{{ row.id }}/answers"' in template
    assert "response_counts.get(row.id, 0)" in template
    assert "quick-xp-card-actions" in template
    assert "grid-template-columns:repeat(3,minmax(0,1fr))!important" in css


def test_card_grids_cancel_adjacent_card_offset_and_stretch_columns():
    css = read("app/web/static/admin.css")
    assert "v1.18.4 — UI alignment" in css
    assert "margin-top:0!important" in css
    assert "align-items:stretch!important" in css
    for token in (".dashboard-duo", ".survey-grid", ".badge-library-grid", ".giveaway-library-grid", ".opportunity-board"):
        assert token in css


def test_notification_filter_actions_are_stable():
    template = read("app/web/templates/notifications.html")
    css = read("app/web/static/admin.css")
    assert 'class="smart-filters notification-filters"' in template
    assert '<button class="primary" type="submit">Застосувати</button>' in template
    assert '<a class="soft-button" href="/admin/notifications">Скинути</a>' in template
    assert ".notification-filters .filter-actions" in css


def test_visible_admin_labels_are_ukrainian_for_known_regressions():
    templates = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app/web/templates").glob("*.html"))
    for forbidden in (
        "Change Control",
        "Data Integrity Center",
        "🧹 Data Integrity",
        "Retention cleanup",
        "Політика retention",
        "privacy-retention scheduler",
        "Запустити retention cleanup",
        "Old → New",
        "Staff-профіль",
    ):
        assert forbidden not in templates
    assert "Контроль правил" in templates
    assert "Цілісність даних" in templates
    assert "Політика зберігання даних" in templates


def test_backup_verification_stays_on_postgresql_18():
    workflow = read(".github/workflows/backup.yml")
    restore = read("scripts/verify_backup_restore.sh")
    assert "image: public.ecr.aws/docker/library/postgres:18" in workflow
    assert "public.ecr.aws/docker/library/postgres:18 pg_restore" in restore
