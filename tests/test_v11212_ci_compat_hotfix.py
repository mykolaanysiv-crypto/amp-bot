from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v11212_release_version_and_static_cache_are_in_sync():
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version.startswith("1.12.1")
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == version
    for rel in (
        "app/web/templates/base.html",
        "app/web/templates/login.html",
        "app/web/templates/login_2fa.html",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert f"?v={version}" in text


def test_historical_tests_do_not_pin_obsolete_release_version():
    offenders = []
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name == __file__.split("/")[-1]:
            continue
        text = path.read_text(encoding="utf-8")
        if '== "1.12.0"' in text or '?v=1.12.0"' in text:
            offenders.append(path.name)
    assert offenders == []


def test_runtime_health_is_explicitly_documented_emergency_delivery_path():
    test_src = (ROOT / "tests/test_v190_notification_center.py").read_text(encoding="utf-8")
    runtime = (ROOT / "app/runtime_health.py").read_text(encoding="utf-8")
    assert '"app/runtime_health.py"' in test_src
    assert "settings.superadmin_ids" in runtime
    assert "await bot.send_message(tg_id, text_value)" in runtime
