from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v11304_version_and_cache_tokens_are_synchronized():
    version = read("VERSION.txt").strip()
    assert version.startswith("1.13.")
    assert read("VERSION_CHECK.txt").strip() == version
    assert f'"{version}"' in read("app/version.py")
    for rel in (
        "app/web/templates/base.html",
        "app/web/templates/login.html",
        "app/web/templates/login_2fa.html",
    ):
        assert f"?v={version}" in read(rel)


def test_notification_center_historical_regression_uses_ukrainian_streak_label():
    route = read("app/web/routes/notifications.py")
    regression = read("tests/test_v190_notification_center.py")
    assert '("streak", "Серії участі")' in route
    assert '"Серії участі"' in regression
    assert '"Streak"' not in regression


def test_smart_opportunities_test_uses_project_clock_not_deprecated_utcnow():
    source = read("tests/test_v192_smart_opportunities_seasons.py")
    assert "from app.time_utils import clock" in source
    assert "deadline=clock.storage_utc()+timedelta(days=10)" in source
    assert "datetime.utcnow()" not in source
