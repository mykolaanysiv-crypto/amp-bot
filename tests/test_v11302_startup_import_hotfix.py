from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def unresolved_relative_imports() -> list[str]:
    issues: list[str] = []
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_module = path.relative_to(ROOT).with_suffix("")
        package_parts = list(rel_module.parts)[:-1]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level or not node.module:
                continue
            up = node.level - 1
            if up > len(package_parts):
                issues.append(f"{path.relative_to(ROOT)}:{node.lineno}:escapes-root")
                continue
            target_parts = package_parts[: len(package_parts) - up] + node.module.split(".")
            module_file = ROOT.joinpath(*target_parts).with_suffix(".py")
            package_init = ROOT.joinpath(*target_parts) / "__init__.py"
            if not module_file.exists() and not package_init.exists():
                issues.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:"
                    f"{'.' * node.level}{node.module}->{'.'.join(target_parts)}"
                )
    return issues


def test_v11302_version_and_schema_head_are_stable():
    version = read("VERSION.txt").strip()
    check = read("VERSION_CHECK.txt").strip()
    assert version == check
    assert tuple(int(part) for part in version.split(".")) >= (1, 13, 0, 2)
    migration = read("migrations/versions/20260915_0002_content_views.py")
    assert 'revision: str = "20260915_0002"' in migration


def test_start_flow_uses_correct_package_depth_for_root_app_modules():
    common = read("app/handlers/start_flow/common.py")
    entry = read("app/handlers/start_flow/entry.py")
    assert "from ...time_utils import clock" in common
    assert "from ...config import Settings" in common
    assert "from ...models import" in common
    assert "from ...services import (" in common
    assert "from ...gamification import get_level" in entry
    assert "from ..time_utils import clock" not in common
    assert "from ..config import Settings" not in common


def test_every_explicit_relative_module_import_resolves():
    assert unresolved_relative_imports() == []


def test_production_preflight_contains_generic_relative_import_guard():
    source = read("scripts/production_preflight.py")
    assert "unresolved_relative_imports" in source
    assert "Startup import preflight failed" in source
    assert "module_file.exists()" in source
    assert "package_init.exists()" in source
