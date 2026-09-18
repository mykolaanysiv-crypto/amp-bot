from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

def test_version_is_v11402_or_newer():
    def parts(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in value.split("."))
    assert parts(read("VERSION.txt").strip()) >= (1, 14, 0, 2)
    assert read("VERSION_CHECK.txt").strip() == read("VERSION.txt").strip()

def test_telegram_profile_explicitly_imports_userrole():
    src = read("app/handlers/participant_home.py")
    assert "UserRole.AMBASSADOR.value" in src
    tree = ast.parse(src)
    assert any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "UserRole" for alias in node.names)
        for node in ast.walk(tree)
    )

def test_profile_still_exposes_ambassador_responsibility_and_hub():
    src = read("app/handlers/participant_home.py")
    assert '@router.message(F.text == "👤 Мій профіль")' in src
    assert "profile_hub_keyboard(user.role)" in src
    assert "ambassador_responsibility" in src

def test_v1140_schema_head_is_unchanged():
    mig = read("migrations/versions/20260917_0003_ambassador_cabinets.py")
    assert 'revision: str = "20260917_0003"' in mig
