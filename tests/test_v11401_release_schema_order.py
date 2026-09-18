from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

def test_version_is_v11401_or_newer():
    version = tuple(map(int, read("VERSION.txt").strip().split(".")))
    version_check = tuple(map(int, read("VERSION_CHECK.txt").strip().split(".")))
    assert version >= (1, 14, 0, 1)
    assert version_check == version

def test_release_smoke_migrates_before_orm_bootstrap():
    src = read("scripts/startup_smoke.py")
    db_init = src.index("asyncio.run(_db_init_phase())")
    migrate = src.index("upgrade_head()", db_init)
    bootstrap = src.index("asyncio.run(_bootstrap_defaults_phase())", migrate)
    web = src.index("asyncio.run(_web_startup_phase())", bootstrap)
    assert db_init < migrate < bootstrap < web
    assert "UndefinedColumnError" in src

def test_v1140_schema_head_is_preserved():
    migration = read("migrations/versions/20260917_0003_ambassador_cabinets.py")
    assert 'revision: str = "20260917_0003"' in migration
    assert 'down_revision: Union[str, None] = "20260915_0002"' in migration

def test_preflight_guards_schema_before_bootstrap_order():
    src = read("scripts/production_preflight.py")
    assert "Release-order preflight failed" in src
    assert "_bootstrap_defaults_phase" in src
