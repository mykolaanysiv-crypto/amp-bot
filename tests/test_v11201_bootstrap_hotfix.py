from pathlib import Path


def test_bootstrap_lock_defined_after_refactor():
    text = Path("app/domain_services/bootstrap.py").read_text()
    assert "_bootstrap_lock = asyncio.Lock()" in text
    assert "async with _bootstrap_lock:" in text


def test_release_phase_still_uses_bootstrap_defaults():
    # v1.12.1 delegates the real lifecycle sequence to startup_smoke.py.
    release = Path("scripts/heroku_release.py").read_text()
    smoke = Path("scripts/startup_smoke.py").read_text()
    assert "startup_smoke()" in release
    assert "await bootstrap_defaults(db, settings)" in smoke


def test_hotfix_is_preserved_in_later_versions():
    version = tuple(int(part) for part in Path("VERSION.txt").read_text().strip().split("."))
    assert version >= (1, 12, 0, 1)
