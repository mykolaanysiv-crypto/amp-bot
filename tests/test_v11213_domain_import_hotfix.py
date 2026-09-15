from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / "app" / "domain_services"


def test_domain_service_single_dot_imports_resolve_to_real_siblings():
    siblings = {path.stem for path in DOMAIN.glob("*.py")}
    offenders: list[str] = []
    for path in DOMAIN.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                module = node.module.split(".", 1)[0]
                if module not in siblings:
                    offenders.append(f"{path.name}:{node.lineno}: .{node.module}")
    assert offenders == []


def test_root_app_dependencies_use_parent_relative_imports_after_refactor():
    bootstrap = (DOMAIN / "bootstrap.py").read_text(encoding="utf-8")
    gamification = (DOMAIN / "gamification.py").read_text(encoding="utf-8")
    events = (DOMAIN / "events.py").read_text(encoding="utf-8")
    assert "from ..settlements import ensure_settlement_directory" in bootstrap
    assert "from ..donations import ensure_donation_badges" in bootstrap
    assert "from ..donations import donation_totals_for_user" in gamification
    assert "from ..reliability import queue_telegram_delivery" in events


def test_version_and_static_cache_are_synchronized():
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert version.startswith("1.12.1")
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == version
    for rel in (
        "app/web/templates/base.html",
        "app/web/templates/login.html",
        "app/web/templates/login_2fa.html",
    ):
        assert f"?v={version}" in (ROOT / rel).read_text(encoding="utf-8")
